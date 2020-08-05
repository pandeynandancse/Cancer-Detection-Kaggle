import os
import torch

import albumentations
import pretrainedmodels

import numpy as np
import pandas as pd
import torch.nn as nn

from apex import amp
from sklearn import metrics
from torch.nn import functional as F

from wtfml.data_loaders.image import ClassificationLoader
from wtfml.engine import Engine
from wtfml.utils import EarlyStopping


class SEResNext50_32x4d(nn.Module):
    def __init__(self, pretrained="imagenet"):
        super(SEResNext50_32x4d, self).__init__()
        #what model will be used 
        self.model = pretrainedmodels.__dict__[
            "se_resnext50_32x4d"
        ](pretrained=pretrained)

        #because skewed data so Area under curve matric will be used so use linear layer. NO need of sigmoid and softmax.
        #any extra layer you want
        self.out = nn.Linear(2048, 1) #2048 is output of layer4 
    
    #forward function defines what you want from each layer of above
    def forward(self, image, targets):
        bs, _, _, _ = image.shape
        #what you want from pretrained model -- here it is output of layer4 that is features of image because 'feature method' contains layers from 1 to 4
        x = self.model.features(image) #outputs features via passing image to layer 1 2,3 and finally 4 and output is of shape 2048 
        x = F.adaptive_avg_pool2d(x, 1)
        #reshape to batch size
        x = x.reshape(bs, -1)
        #pass through out layer
        out = self.out(x)
        #because model(), that has been called inside evaluate function of wtfml - Engine library, returns 'predctions and loss' both so define 'loss' here also. 
        loss = nn.BCEWithLogitsLoss()(
            out, targets.reshape(-1, 1).type_as(out)
        )
        return out, loss


def train(fold):
    training_data_path = "./melanoma/input/jpeg/train224/"
    model_path = "./melanoma-deep-learning"
    df = pd.read_csv("./melanoma/input/train_folds.csv")
    device = "cuda"
    epochs = 50
    train_bs = 32
    valid_bs = 16
    mean = (0.485, 0.456, 0.406)
    std = (0.229, 0.224, 0.225)

    df_train = df[df.kfold != fold].reset_index(drop=True)
    df_valid = df[df.kfold == fold].reset_index(drop=True)

    train_aug = albumentations.Compose(
        [
            albumentations.Normalize(mean, std, max_pixel_value=255.0, always_apply=True),
        ]
    )

    valid_aug = albumentations.Compose(
        [
            albumentations.Normalize(mean, std, max_pixel_value=255.0, always_apply=True),
        ]
    )

    train_images = df_train.image_name.values.tolist()
    train_images = [os.path.join(training_data_path, i + ".jpg") for i in train_images]
    train_targets = df_train.target.values

    valid_images = df_valid.image_name.values.tolist()
    valid_images = [os.path.join(training_data_path, i + ".jpg") for i in valid_images]
    valid_targets = df_valid.target.values

    train_dataset = ClassificationLoader(
        image_paths=train_images,
        targets=train_targets,
        resize=None,
        augmentations=train_aug
    )

    train_loader = torch.utils.data.DataLoader(
        train_dataset,
        batch_size=train_bs,
        shuffle=True,
        num_workers=4
    )

    valid_dataset = ClassificationLoader(
        image_paths=valid_images,
        targets=valid_targets,
        resize=None,
        augmentations=valid_aug
    )

    valid_loader = torch.utils.data.DataLoader(
        valid_dataset,
        batch_size=valid_bs,
        shuffle=False,
        num_workers=4
    )

    model = SEResNext50_32x4d(pretrained="imagenet")
    model.to(device)

    optimizer = torch.optim.Adam(model.parameters(), lr=1e-4)
    #mode = 'max' becoz area under curve metrics must be maximum
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer,
        patience=3,
        mode="max"
    )
    #apex is from nvidia ---- for mixed precision training ---- train little faster without occupying to much memory  ---- you can skip it if you don't want
    model, optimizer = amp.initialize(
        model,
        optimizer,
        opt_level="O1",
        verbosity=0
    )

    es = EarlyStopping(patience=5, mode="max")
    for epoch in range(epochs):
        training_loss = Engine.train(
            train_loader, 
            model,
            optimizer,
            device,
            fp16=True
        )
        predictions, valid_loss = Engine.evaluate(
            train_loader, 
            model,
            optimizer,
            device
        )
        predictions = np.vstack((predictions)).ravel()
        auc = metrics.roc_auc_score(valid_targets, predictions)
        scheduler.step(auc)
        print(f"epoch={epoch}, auc={auc}")
        es(auc, model, os.path.join(model_path, f"model{fold}.bin"))
        if es.early_stop:
            print("early stopping")
            break


def predict(fold):
    test_data_path = "./melanoma/input/jpeg/test224/"
    model_path = "./melanoma-deep-learning"
    df_test = pd.read_csv("./melanoma/input/test.csv")
    df_test.loc[:, "target"] = 0

    device = "cuda"
    epochs = 50
    test_bs = 16
    mean = (0.485, 0.456, 0.406)
    std = (0.229, 0.224, 0.225)

    test_aug = albumentations.Compose(
        [
            albumentations.Normalize(mean, std, max_pixel_value=255.0, always_apply=True),
        ]
    )

    test_images = df_test.image_name.values.tolist()
    test_images = [os.path.join(test_data_path, i + ".jpg") for i in test_images]
    test_targets = df_test.target.values

    test_dataset = ClassificationLoader(
        image_paths=test_images,
        targets=test_targets,
        resize=None,
        augmentations=test_aug
    )

    test_loader = torch.utils.data.DataLoader(
        test_dataset,
        batch_size=test_bs,
        shuffle=False,
        num_workers=4
    )

    model = SEResNext50_32x4d(pretrained="imagenet")
    model.load_state_dict(torch.load(os.path.join(model_path, f"model{fold}.bin")))
    model.to(device)

    predictions = Engine.predict(
        test_loader,
        model,
        device
    )
    return np.vstack((predictions)).ravel()


if __name__ == "__main__":
    train(fold=0)
    predict(fold=0)
