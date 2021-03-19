This repository is for **Paper 6674, Delving into Effective Gradient Matching for Dataset Condensation** as a ICCV 2021 submission. We adapt the [original implementation](https://github.com/VICO-UoE/DatasetCondensation). Please refer to the [original README file](https://github.com/VICO-UoE/DatasetCondensation/blob/master/readme.md) for more experimental settings.

# Our proposed method
We implement different gradient matching methods in four python scripts.
* `baseline.py`: intra-class gradient matching
* `inter-class.py`: inter-class gradient matching
* `interleaved.py`: matching intra-class and inter-class gradients in an interleaved way
* `multi-level.py`: multi-level gradient matching

Users can customize the distance functions in `distance_improved` defined in `utils.py`.
The argument `--dis_metric baseline` or `--dis_metric improved` can be set accordingly.

With argument `--adaptive_step`, the adaptive learning step is enabled.
Otherwise, we will use the original learning step. 

# How to reproduce our result

## Table 1
```
python baseline.py     --dataset CIFAR10  --ipc 10
python inter-class.py  --dataset CIFAR10  --ipc 10
python interleaved.py  --dataset CIFAR10  --ipc 10
python multi-level.py  --dataset CIFAR10  --ipc 10
# --dataset: MNIST, FashionMNIST, SVHN, CIFAR10, CIFAR100
# --ipc (images per class): 1, 10, 20, 30, 40, 50
```

## Table 2
The function of `distance_improved` in `utils.py` can be customized.
```
python multi-level.py  --dataset CIFAR10  --ipc 10 --dis_metric baseline
python multi-level.py  --dataset CIFAR10  --ipc 10 --dis_metric improved
```

## Table 3

```
baseline: python baseline.py     --dataset CIFAR10  --ipc 10
Ours-M:   python multi-level.py  --dataset CIFAR10  --ipc 10
Ours-MD:  python multi-level.py  --dataset CIFAR10  --ipc 10  --dis_metric improved 
Ours-MDA: python multi-level.py  --dataset CIFAR10  --ipc 10  --dis_metric improved  --adaptive_step 
# --dataset: MNIST, FashionMNIST, SVHN, CIFAR10, CIFAR100
# --ipc (images per class): 1, 10, 20, 30, 40, 50
```

## Table 4
```
python multi-level.py  --dataset MNIST  --ipc 1  --dis_metric improved  --adaptive_step  --model ConvNet  --eval_mode M
# --model: MLP, LeNet, ConvNet, AlexNet, VGG11BN, ResNet18BN_AP
# set --lr_img 0.01 when --model MLP
```
