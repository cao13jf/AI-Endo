import os
import pickle
import random
import logging
import shutil
import argparse
import numpy as np
import pandas as pd
from tqdm import tqdm
from glob import glob
from sklearn import metrics

import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from model.mstcn import MultiStageModel
from model.transformer import Transformer
from dataset.esd import VideoSample

from utils.parser import ParserUse
from utils.util import plot_class_band


phase_dict = {}
phase_dict_key = ['idle', 'marking', 'injection', 'dissection']
for i in range(len(phase_dict_key)):
    phase_dict[phase_dict_key[i]] = i

label_dict = {}
phase_dict_key = ['idle', 'marking', 'injection', 'dissection']
for i, phase in enumerate(phase_dict_key):
    label_dict[i] = phase


def test_model(args):
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed(args.seed)
    logging.info("\n\n\n" + "|| "*10 + "Begin testing model")

    fusion_model = MultiStageModel(args.mstcn_stages, args.mstcn_layers, args.mstcn_f_maps, args.mstcn_f_dim, args.out_classes, True, is_train=False)
    fusion_model.load_state_dict(torch.load(args.fusion_model), strict=True)
    fusion_model.cuda()
    fusion_model.eval()

    trans_model = Transformer(args.mstcn_f_maps, args.mstcn_f_dim, args.out_classes, args.trans_seq, d_model=args.mstcn_f_maps)
    trans_model.load_state_dict(torch.load(args.trans_model))
    trans_model.cuda()
    trans_model.eval()

    with open(args.data_file, "rb") as f:
        data_dict = pickle.load(f)
    with open(args.emb_file, "rb") as f:
        emb_dict = pickle.load(f)

    test_data = VideoSample(data_dict=data_dict, data_idxs=args.test_names, data_features=emb_dict, is_train=False, get_name=True)
    test_loader = DataLoader(test_data, batch_size=1, shuffle=False, num_workers=0, drop_last=False)

    if not os.path.isdir(args.pred_folder):
        os.makedirs(args.pred_folder)

    pred_label_files = []
    with torch.no_grad():
        for data in tqdm(test_loader, desc="Predicting"):
            img_featrues0, img_names = data[0].cuda(non_blocking=True), data[1]
            img_featrues = torch.transpose(img_featrues0, 1, 2)
            features = fusion_model(img_featrues).squeeze(1)  # Shifted predictions for all frames

            # [1, 32, 2321]. [1, 2321, 2048]
            p_classes = trans_model(features.detach(), img_featrues0).squeeze()
            preds = torch.argmax(p_classes, dim=-1).cpu().numpy().tolist()
            p_classes = p_classes.cpu().numpy()
            pd_label = pd.DataFrame({"Frame": list(range(1, len(preds)+1, 1)),
                                     "Phase": preds,
                                     "Idle": p_classes[:, 0].tolist(),
                                     "Marking": p_classes[:, 1].tolist(),
                                     "Injection": p_classes[:, 2].tolist(),
                                     "Dissection": p_classes[:, 3].tolist()})
            pd_label = pd_label.astype({"Frame": "int",
                                        "Phase": "int",
                                        "Idle": "float",
                                        "Marking": "float",
                                        "Injection": "float",
                                        "Dissection": "float"}).replace({"Phase": label_dict})
            if "--" in img_names[0][0]:
                base_name = os.path.basename(args.trans_model).split("_")[-1].split(".")[0] + "_T_" + os.path.basename(img_names[0][0].split("--")[0]) + ".txt"
            else:
                base_name = os.path.basename(args.trans_model).split("_")[-1].split(".")[0] + "_T_" + os.path.basename(img_names[0][0].split("-")[0]) + ".txt"
            save_file = os.path.join(args.pred_folder, base_name)
            pd_label.to_csv(save_file, index=False, header=None, sep="\t")
            pred_label_files.append(save_file)
    print("Finished")
    accs = []
    for pred_label_file in pred_label_files:
        base_name = os.path.basename(pred_label_file)
        gt_label_file = os.path.join(args.label_dir, os.path.basename(pred_label_file).split('_T_')[-1])

        gt_label = pd.read_csv(gt_label_file, header=None, sep="\t", names=["Frame", "Phase"], index_col=False)
        gt_label = gt_label.replace({"Phase": phase_dict})
        gt_label = gt_label["Phase"].tolist()
        pred_label = pd.read_csv(pred_label_file, header=None, sep="\t", names=["Frame", "Phase"], index_col=False)
        pred_label = pred_label.replace({"Phase": phase_dict})
        pred_label = pred_label["Phase"].tolist()
        logging.info(">> " * 10 + base_name)
        acc = metrics.accuracy_score(gt_label, pred_label)
        accs.append(acc)
        logging.info("Accuracy {:>10.5f}".format(acc))
        # logging.info("Precision {:>10.5f}\n".format(metrics.precision_score(gt_label, pred_label, average='micro')))
        # plot_class_band(gt_label, pred_label, os.path.join(args.pred_folder, base_name.replace(".txt", ".pdf")), "{:>4.3f}".format(acc))
    print("|| "*10, "Mean: {:10.5f}".format(sum(accs) / len(accs)))
    return args


if __name__ == "__main__":

    args = argparse.ArgumentParser()
    args.add_argument("--cfg", default="train", required=True, type=str, help="Config file")
    args.add_argument("-n", default="", help="Note for testing")

    args = args.parse_args()
    args = ParserUse(args.cfg, "test").add_args(args)

    args.makedir()
    logging.info(args)
    logging.info("=" * 20 + "\n\n\n")

    test_model(args)




