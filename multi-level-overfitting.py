import os
import copy
import argparse
import numpy as np
import torch
import torch.nn as nn
from torchvision.utils import save_image
from utils import get_loops, get_dataset, get_network, get_eval_pool, evaluate_synset, get_daparam, match_loss, get_time, TensorDataset, epoch


def main():

    parser = argparse.ArgumentParser(description='Parameter Processing')
    parser.add_argument('--dataset', type=str, default='CIFAR10', help='dataset')
    parser.add_argument('--model', type=str, default='ConvNet', help='model')
    parser.add_argument('--ipc', type=int, default=1, help='image(s) per class')
    # S: the same to training model, M: multi architectures,  W: net width, D: net depth, A: activation function, P: pooling layer, N: normalization layer,
    parser.add_argument('--eval_mode', type=str, default='S', help='eval_mode')
    parser.add_argument('--num_exp', type=int, default=5, help='the number of experiments')
    parser.add_argument('--num_eval', type=int, default=20, help='the number of evaluating randomly initialized models')
    parser.add_argument('--epoch_eval_train', type=int, default=300, help='epochs to train a model with synthetic data')
    parser.add_argument('--Iteration', type=int, default=1000, help='training iterations')
    parser.add_argument('--lr_img', type=float, default=0.1, help='learning rate for updating synthetic images')
    parser.add_argument('--lr_net', type=float, default=0.01, help='learning rate for updating network parameters')
    parser.add_argument('--batch_real', type=int, default=256, help='batch size for real data')
    parser.add_argument('--batch_train', type=int, default=256, help='batch size for training networks')
    parser.add_argument('--init', type=str, default='noise', help='initialization of synthetic data, noise/real: initialize from random noise or real images. The two initializations will get similar performances.')
    parser.add_argument('--data_path', type=str, default='../data', help='dataset path')
    parser.add_argument('--save_path', type=str, default='result', help='path to save results')
    parser.add_argument('--dis_metric', type=str, default='baseline', help='distance metric')
    parser.add_argument('--adaptive_step', dest='adaptive_step', action='store_true', help='If enabled, the adaptive learning step is used.')
    parser.add_argument('--file_name_prefix', type=str, default='multi-level-overfitting', help='the prefix name of the generated file (png file and pt file)')
    # For speeding up, we can decrease the Iteration and epoch_eval_train, which will not cause significant performance decrease.

    args = parser.parse_args()
    args.outer_loop, args.inner_loop = get_loops(args.ipc)
    args.device = 'cuda' if torch.cuda.is_available() else 'cpu'

    if not os.path.exists(args.data_path):
        os.mkdir(args.data_path)

    if not os.path.exists(args.save_path):
        os.mkdir(args.save_path)

    eval_it_pool = np.arange(500, args.Iteration+1, 500).tolist() if args.eval_mode == 'S' else [args.Iteration]  # The list of iterations when we evaluate models and record results.
    channel, im_size, num_classes, class_names, mean, std, dst_train, dst_test, trainloader_real, testloader = get_dataset(args.dataset, args.data_path, args.batch_real)
    iter_trainloader_real = iter(trainloader_real)
    model_eval_pool = get_eval_pool(args.eval_mode, args.model, args.model)

    accs_all_exps = dict()  # record performances of all experiments
    for key in model_eval_pool:
        accs_all_exps[key] = []

    data_save = []

    for exp in range(args.num_exp):
        print('\n================== Exp %d ==================\n ' % exp)
        print('Hyper-parameters: \n', args.__dict__)
        print('Evaluation model pool: ', model_eval_pool)

        ''' organize the real dataset '''
        images_all = []
        labels_all = []
        indices_class = [[] for c in range(num_classes)]

        images_all = [torch.unsqueeze(dst_train[i][0], dim=0) for i in range(len(dst_train))]
        labels_all = [dst_train[i][1] for i in range(len(dst_train))]
        for i, lab in enumerate(labels_all):
            indices_class[lab].append(i)
        images_all = torch.cat(images_all, dim=0).to(args.device)
        labels_all = torch.tensor(labels_all, dtype=torch.long, device=args.device)

        for c in range(num_classes):
            print('class c = %d: %d real images' % (c, len(indices_class[c])))

        def get_images(c, n):  # get random n images from class c
            idx_shuffle = np.random.permutation(indices_class[c])[:n]
            return images_all[idx_shuffle]

        for ch in range(channel):
            print('real images channel %d, mean = %.4f, std = %.4f' % (ch, torch.mean(images_all[:, ch]), torch.std(images_all[:, ch])))

        ''' initialize the synthetic data '''
        image_syn = torch.randn(size=(num_classes*args.ipc, channel, im_size[0], im_size[1]), dtype=torch.float, requires_grad=True, device=args.device)
        label_syn = torch.tensor([np.ones(args.ipc)*i for i in range(num_classes)], dtype=torch.long, requires_grad=False, device=args.device).view(-1)  # [0,0,0, 1,1,1, ..., 9,9,9]

        if args.init == 'real':
            print('initialize synthetic data from random real images')
            for c in range(num_classes):
                image_syn.data[c*args.ipc:(c+1)*args.ipc] = get_images(c, args.ipc).detach().data
        else:
            print('initialize synthetic data from random noise')

        ''' training '''
        optimizer_img = torch.optim.SGD([image_syn, ], lr=args.lr_img, momentum=0.5)  # optimizer_img for synthetic data
        optimizer_img.zero_grad()
        criterion = nn.CrossEntropyLoss().to(args.device)
        print('%s training begins' % get_time())

        for it in range(args.Iteration+1):

            ''' Evaluate synthetic data '''
            if it in eval_it_pool:
                for model_eval in model_eval_pool:
                    print('-------------------------\nEvaluation\nmodel_train = %s, model_eval = %s, iteration = %d' % (args.model, model_eval, it))
                    param_augment = get_daparam(args.dataset, args.model, model_eval, args.ipc)
                    if param_augment['strategy'] != 'none':
                        epoch_eval_train = 1000  # More epochs for evaluation with augmentation will be better.
                        print('data augmentation = %s' % param_augment)
                    else:
                        epoch_eval_train = args.epoch_eval_train
                    accs = []
                    for it_eval in range(args.num_eval):
                        net_eval = get_network(model_eval, channel, num_classes, im_size).to(args.device)  # get a random model
                        image_syn_eval, label_syn_eval = copy.deepcopy(image_syn.detach()), copy.deepcopy(label_syn.detach())  # avoid any unaware modification
                        _, acc_train, acc_test = evaluate_synset(it_eval, net_eval, image_syn_eval, label_syn_eval, testloader, args.lr_net,
                                                                 args.batch_train, param_augment, args.device, epoch_eval_train)
                        accs.append(acc_test)
                    print('Evaluate %d random %s, mean = %.4f std = %.4f\n-------------------------' % (len(accs), model_eval, np.mean(accs), np.std(accs)))

                    if it == args.Iteration:  # record the final results
                        accs_all_exps[model_eval] += accs

                ''' visualize and save '''
                save_name = os.path.join(args.save_path, '%s_%s_%s_%dipc_exp%d_iter%d.png' % (args.file_name_prefix, args.dataset, args.model, args.ipc, exp, it))
                image_syn_vis = copy.deepcopy(image_syn.detach().cpu())
                for ch in range(channel):
                    image_syn_vis[:, ch] = image_syn_vis[:, ch] * std[ch] + mean[ch]
                image_syn_vis[image_syn_vis < 0] = 0.0
                image_syn_vis[image_syn_vis > 1] = 1.0
                save_image(image_syn_vis, save_name, nrow=args.ipc)  # Trying normalize = True/False may get better visual effects.
                # The generated images would be slightly different from the visualization results in the paper, because of the initialization and normalization of pixels.

            ''' Train synthetic data '''
            net = get_network(args.model, channel, num_classes, im_size).to(args.device)  # get a random model
            net.train()
            net_parameters = list(net.parameters())
            optimizer_net = torch.optim.SGD(net.parameters(), lr=args.lr_net, momentum=0.5)  # optimizer_img for synthetic data
            optimizer_net.zero_grad()
            loss_avg = 0

            for ol in range(args.outer_loop):

                ''' freeze the running mu and sigma for BatchNorm layers '''
                # Synthetic data batch, e.g. only 1 image/batch, is too small to obtain stable mu and sigma.
                # So, we calculate and freeze mu and sigma for BatchNorm layer with real data batch ahead.
                # This would make the training with BatchNorm layers easier.

                BN_flag = False
                BNSizePC = 16  # for batch normalization
                for module in net.modules():
                    if 'BatchNorm' in module._get_name():  # BatchNorm
                        BN_flag = True
                if BN_flag:
                    img_real = torch.cat([get_images(c, BNSizePC) for c in range(num_classes)], dim=0)
                    net.train()  # for updating the mu, sigma of BatchNorm
                    output_real = net(img_real)  # get running mu, sigma
                    for module in net.modules():
                        if 'BatchNorm' in module._get_name():  # BatchNorm
                            module.eval()  # fix mu and sigma of every BatchNorm layer

                ''' update synthetic data '''
                loss = torch.tensor(0.0).to(args.device)
                gw_real_vec = list(0.0 for _ in net_parameters)
                gw_syn_vec = list(0.0 for _ in net_parameters)
                for c in range(num_classes):
                    img_real = get_images(c, args.batch_real)
                    lab_real = torch.ones((img_real.shape[0],), device=args.device, dtype=torch.long) * c
                    output_real = net(img_real)
                    loss_real = criterion(output_real, lab_real)
                    gw_real = torch.autograd.grad(loss_real, net_parameters)
                    gw_real = list((_.detach().clone() for _ in gw_real))
                    for i, grad in enumerate(gw_real):
                        gw_real_vec[i] += grad

                    img_syn = image_syn[c*args.ipc:(c+1)*args.ipc].reshape((args.ipc, channel, im_size[0], im_size[1]))
                    lab_syn = torch.ones((args.ipc,), device=args.device, dtype=torch.long) * c
                    output_syn = net(img_syn)
                    loss_syn = criterion(output_syn, lab_syn)
                    gw_syn = torch.autograd.grad(loss_syn, net_parameters, create_graph=True)
                    for i, grad in enumerate(gw_syn):
                        gw_syn_vec[i] += grad

                    loss += match_loss(gw_syn, gw_real, args.dis_metric)

                for i in range(len(gw_real)):
                    gw_real_vec[i] /= num_classes
                    gw_syn_vec[i] /= num_classes
                loss += num_classes * match_loss(gw_syn_vec, gw_real_vec, args.dis_metric)

                optimizer_img.zero_grad()
                loss.backward()
                optimizer_img.step()
                loss_avg += loss.item()

                if ol == args.outer_loop - 1:
                    break

                try:
                    img_real, lab_real = iter_trainloader_real.next()
                except:
                    iter_trainloader_real = iter(trainloader_real)
                    img_real, lab_real = iter_trainloader_real.next()
                img_real, lab_real = img_real.to(args.device), lab_real.to(args.device)

                ''' update network '''
                image_syn_train, label_syn_train = copy.deepcopy(image_syn.detach()), copy.deepcopy(label_syn.detach())  # avoid any unaware modification
                dst_syn_train_copy = TensorDataset(image_syn_train, label_syn_train)
                trainloader = torch.utils.data.DataLoader(dst_syn_train_copy, batch_size=args.batch_train, shuffle=True, num_workers=0)

                with torch.no_grad():
                    previous_validation_loss = criterion(net(img_real), lab_real)
                inner_loop = 0
                while True:
                    inner_loop += 1
                    train_loss, _ = epoch('train', trainloader, net, optimizer_net, criterion, None, args.device)
                    with torch.no_grad():
                        current_validation_loss = criterion(net(img_real), lab_real)
                    if current_validation_loss > previous_validation_loss or inner_loop == 50:
                        break
                    previous_validation_loss = current_validation_loss
                print(it, ol, inner_loop, train_loss, current_validation_loss)

            loss_avg /= (num_classes * args.outer_loop)

            if it % 10 == 0:
                print('%s iter = %04d, loss = %.4f' % (get_time(), it, loss_avg))

            if it == args.Iteration:  # only record the final results
                data_save.append([copy.deepcopy(image_syn.detach().cpu()), copy.deepcopy(label_syn.detach().cpu())])
                torch.save({'data': data_save, 'accs_all_exps': accs_all_exps, }, os.path.join(args.save_path, '%s_%s_%s_%dipc.pt' % (args.file_name_prefix, args.dataset, args.model, args.ipc)))

    print('\n==================== Final Results ====================\n')
    for key in model_eval_pool:
        accs = accs_all_exps[key]
        print('Run %d experiments, train on %s, evaluate %d random %s, mean  = %.2f%%  std = %.2f%%' % (args.num_exp, args.model, len(accs), key, np.mean(accs)*100, np.std(accs)*100))


if __name__ == '__main__':
    main()
