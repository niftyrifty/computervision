# -*- coding: utf-8 -*-
"""eecs442_final_final.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1yxnpVGc67_aqOUr9g_9iTC_4xj3lDFUB
"""

from scipy.misc import imread, imresize
import os
import numpy as np
import json
import h5py
import torch
from tqdm import tqdm
from collections import Counter
from random import seed, choice, sample
import torch.backends.cudnn as cudnn
import torch.optim
import torch.utils.data
import torchvision
import torchvision.transforms as transforms
from torch.utils.data import Dataset
from torch import nn
from torch.nn.utils.rnn import pack_padded_sequence

"""DATASET DOWNLOAD: This section is downloading coco datasets"""

!wget http://images.cocodataset.org/zips/train2014.zip

!wget http://images.cocodataset.org/zips/val2014.zip

!unzip train2014.zip

!unzip val2014.zip

!wget http://images.cocodataset.org/annotations/annotations_trainval2014.zip

!unzip annotations_trainval2014.zip

!wget https://www.dropbox.com/s/jag01i4760ub6yj/caption_datasets.zip

!unzip caption_datasets.zip

"""LOSS TRACKER: This class is used to update loss values for each epoch"""

class Tracker(object):
    
    def __init__(self):
        self.val = 0
        self.sum = 0
        self.count = 0
        self.avg = 0
        
    def update(self, val, n=1):
        self.val = val
        self.sum += val * n
        self.count += n
        self.avg = self.sum / self.count

"""INPUT FILE: This section is creating input file for the model. Resizing to 256x256 and storing annotations into HDF5 file for simplified work"""

dataset_name = 'dataset_coco.json'
each_image_caption = 5
min_word_freq = 5
maximum_length = 50

with open(dataset_name, 'r') as j:
    data = json.load(j)

train_path = []
train_captions = []
validation_path = []
validation_captions = []
test_paths = []
test_captions = []
unique_word_counter = Counter()

for img in data['images']:
    caption_for_image = []
    for c in img['sentences']:
        unique_word_counter.update(c['tokens'])
        if len(c['tokens']) <= maximum_length:
            caption_for_image.append(c['tokens'])

    if len(caption_for_image) == 0:
        continue

    path = os.path.join(img['filepath'], img['filename'])

    if img['split'] in {'train', 'restval'}:
        train_path.append(path)
        train_captions.append(caption_for_image)
    elif img['split'] in {'val'}:
        validation_path.append(path)
        validation_captions.append(caption_for_image)
    elif img['split'] in {'test'}:
        test_paths.append(path)
        test_captions.append(caption_for_image)

words = [w for w in unique_word_counter.keys() if unique_word_counter[w] > min_word_freq]
word_mapping = {k: v + 1 for v, k in enumerate(words)}
word_mapping['<unk>'] = len(word_mapping) + 1
word_mapping['<start>'] = len(word_mapping) + 1
word_mapping['<end>'] = len(word_mapping) + 1
word_mapping['<pad>'] = 0

with open(os.path.join('WORDMAP.json'), 'w') as j:
    json.dump(word_mapping, j)

seed(123)
for impaths, imcaps, split in [(train_path, train_captions, 'TRAIN'),
                               (validation_path, validation_captions, 'VAL'),
                               (test_paths, test_captions, 'TEST')]:

    with h5py.File(os.path.join(split + '_IMAGES.hdf5'), 'a') as h:
        h.attrs['each_image_caption'] = each_image_caption
        images = h.create_dataset('images', (len(impaths), 3, 256, 256), dtype='uint8')
        enc_captions = []
        caplens = []

        for i, path in enumerate(tqdm(impaths)):
            if len(imcaps[i]) < each_image_caption:
                caption_for_image = imcaps[i] + [choice(imcaps[i]) for _ in range(each_image_caption - len(imcaps[i]))]
            else:
                caption_for_image = sample(imcaps[i], k=each_image_caption)

            img = imread(impaths[i])
            if len(img.shape) == 2:
                img = img[:, :, np.newaxis]
                img = np.concatenate([img, img, img], axis=2)
            img = imresize(img, (256, 256))
            img = img.transpose(2, 0, 1)
            images[i] = img

            for j, c in enumerate(caption_for_image):
                enc_c = [word_mapping['<start>']] + [word_mapping.get(word, word_mapping['<unk>']) for word in c] + [
                    word_mapping['<end>']] + [word_mapping['<pad>']] * (maximum_length - len(c))

                c_len = len(c) + 2

                enc_captions.append(enc_c)
                caplens.append(c_len)

        with open(os.path.join(split + '_CAPTIONS.json'), 'w') as j:
            json.dump(enc_captions, j)

        with open(os.path.join(split + '_CAPLENS.json'), 'w') as j:
            json.dump(caplens, j)

"""DATASET: creating dataset which is loadable for training"""

class CaptionDataset(Dataset):
    def __init__(self, data_folder, data_name, split, transform=None):
        self.split = split
        assert self.split in {'TRAIN', 'VAL', 'TEST'}
        self.h = h5py.File(os.path.join(data_folder, self.split + '_IMAGES_.hdf5'), 'r')
        self.imgs = self.h['images']
        self.cpi = self.h.attrs['each_image_caption']
        with open(os.path.join(data_folder, self.split + '_CAPTIONS_' + data_name + '.json'), 'r') as j:
            self.caption_for_image = json.load(j)
        with open(os.path.join(data_folder, self.split + '_CAPLENS_' + data_name + '.json'), 'r') as j:
            self.caplens = json.load(j)
        self.transform = transform
        self.dataset_size = len(self.caption_for_image)

    def __getitem__(self, i):
        
        img = torch.FloatTensor(self.imgs[i // self.cpi] / 255.)
        if self.transform is not None:
            img = self.transform(img)

        caption = torch.LongTensor(self.caption_for_image[i])

        caplen = torch.LongTensor([self.caplens[i]])

        if self.split is 'TRAIN':
            return img, caption, caplen
        else:
            all_captions = torch.LongTensor(
                self.caption_for_image[((i // self.cpi) * self.cpi):(((i // self.cpi) * self.cpi) + self.cpi)])
            return img, caption, caplen, all_captions

    def __len__(self):
        return self.dataset_size

"""MODELS: CNN and LSTM are implemented here"""

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")


class Encoder(nn.Module):
    """
    Encoder.
    """

    def __init__(self, encoded_image_size=14):
        super(Encoder, self).__init__()
        self.enc_image_size = encoded_image_size

        resnet = torchvision.models.resnet152(pretrained=True) 
        modules = list(resnet.children())[:-2]
        self.resnet = nn.Sequential(*modules)

        self.adaptive_pool = nn.AdaptiveAvgPool2d((encoded_image_size, encoded_image_size))

        self.fine_tune()

    def forward(self, images):
        
        out = self.resnet(images)
        out = self.adaptive_pool(out)
        out = out.permute(0, 2, 3, 1)
        return out

    def fine_tune(self, fine_tune=True):
        
        for p in self.resnet.parameters():
            p.requires_grad = False
        for c in list(self.resnet.children())[5:]:
            for p in c.parameters():
                p.requires_grad = fine_tune


class Attention(nn.Module):

    def __init__(self, encoder_dim, decoder_dim, attention_dim):
        
        super(Attention, self).__init__()
        self.encoder_att = nn.Linear(encoder_dim, attention_dim)
        self.decoder_att = nn.Linear(decoder_dim, attention_dim)
        self.full_att = nn.Linear(attention_dim, 1)
        self.relu = nn.ReLU()
        self.softmax = nn.Softmax(dim=1)

    def forward(self, encoder_out, decoder_hidden):
        
        att1 = self.encoder_att(encoder_out)
        att2 = self.decoder_att(decoder_hidden)
        att = self.full_att(self.relu(att1 + att2.unsqueeze(1))).squeeze(2)
        alpha = self.softmax(att)
        attention_weighted_encoding = (encoder_out * alpha.unsqueeze(2)).sum(dim=1)

        return attention_weighted_encoding, alpha


class DecoderWithAttention(nn.Module):
    def __init__(self, attention_dim, embed_dim, decoder_dim, vocab_size, encoder_dim=2048, dropout=0.5):
        
        super(DecoderWithAttention, self).__init__()

        self.encoder_dim = encoder_dim
        self.attention_dim = attention_dim
        self.embed_dim = embed_dim
        self.decoder_dim = decoder_dim
        self.vocab_size = vocab_size
        self.dropout = dropout

        self.attention = Attention(encoder_dim, decoder_dim, attention_dim)

        self.embedding = nn.Embedding(vocab_size, embed_dim) 
        self.dropout = nn.Dropout(p=self.dropout)
        self.decode_step = nn.LSTMCell(embed_dim + encoder_dim, decoder_dim, bias=True)
        self.init_h = nn.Linear(encoder_dim, decoder_dim)
        self.init_c = nn.Linear(encoder_dim, decoder_dim)
        self.f_beta = nn.Linear(decoder_dim, encoder_dim)
        self.sigmoid = nn.Sigmoid()
        self.fc = nn.Linear(decoder_dim, vocab_size)  
        self.init_weights()
        
    def init_weights(self):
        
        self.embedding.weight.data.uniform_(-0.1, 0.1)
        self.fc.bias.data.fill_(0)
        self.fc.weight.data.uniform_(-0.1, 0.1)

    def load_pretrained_embeddings(self, embeddings):
        
        self.embedding.weight = nn.Parameter(embeddings)

    def fine_tune_embeddings(self, fine_tune=True):
        
        for p in self.embedding.parameters():
            p.requires_grad = fine_tune

    def init_hidden_state(self, encoder_out):
        
        mean_encoder_out = encoder_out.mean(dim=1)
        h = self.init_h(mean_encoder_out)
        c = self.init_c(mean_encoder_out)
        return h, c

    def forward(self, encoder_out, encoded_captions, caption_lengths):

        batch_size = encoder_out.size(0)
        encoder_dim = encoder_out.size(-1)
        vocab_size = self.vocab_size
        encoder_out = encoder_out.view(batch_size, -1, encoder_dim)
        num_pixels = encoder_out.size(1)

        caption_lengths, sort_ind = caption_lengths.squeeze(1).sort(dim=0, descending=True)
        encoder_out = encoder_out[sort_ind]
        encoded_captions = encoded_captions[sort_ind]
        
        embeddings = self.embedding(encoded_captions)
        
        h, c = self.init_hidden_state(encoder_out)
        
        decode_lengths = (caption_lengths - 1).tolist()

        predictions = torch.zeros(batch_size, max(decode_lengths), vocab_size).to(device)
        alphas = torch.zeros(batch_size, max(decode_lengths), num_pixels).to(device)
        for t in range(max(decode_lengths)):
            batch_size_t = sum([l > t for l in decode_lengths])
            attention_weighted_encoding, alpha = self.attention(encoder_out[:batch_size_t],
                                                                h[:batch_size_t])
            gate = self.sigmoid(self.f_beta(h[:batch_size_t]))
            attention_weighted_encoding = gate * attention_weighted_encoding
            h, c = self.decode_step(
                torch.cat([embeddings[:batch_size_t, t, :], attention_weighted_encoding], dim=1),
                (h[:batch_size_t], c[:batch_size_t]))
            preds = self.fc(self.dropout(h))
            predictions[:batch_size_t, t, :] = preds
            alphas[:batch_size_t, t, :] = alpha

        return predictions, encoded_captions, decode_lengths, alphas, sort_ind

"""TRAINING: Model is trained here"""

attention_dim = 512
decoder_dim = 512
emb_dim = 512
dropout = 0.5
encoder_lr = 1e-4
decoder_lr = 4e-4
start_epoch = 0
workers = 1
grad_clip_range = 5.
batch_size = 256
alpha_c = 1.
print_freq = 50
fine_tune_encoder = False
checkpoint = None

device = torch.device("cuda" if torch.cuda.is_available() else "cpu") 

def main():
    
    global start_epoch, fine_tune_encoder, word_mapping, epochs_since_improvement, checkpoint
    word_file = os.path.join(data_folder, 'WORDMAP.json')
    with open(word_file, 'r') as j:
        word_mapping = json.load(j)

    decoder = DecoderWithAttention(attention_dim=attention_dim,
                                   embed_dim=emb_dim,
                                   decoder_dim=decoder_dim,
                                   vocab_size=len(word_mapping),
                                   dropout=dropout)
    decoder_optimizer = torch.optim.Adam(params=filter(lambda p: p.requires_grad, decoder.parameters()),
                                         lr=decoder_lr)
    encoder = Encoder()
    encoder.fine_tune(fine_tune_encoder)
    encoder_optimizer = torch.optim.Adam(params=filter(lambda p: p.requires_grad, encoder.parameters()),
                                         lr=encoder_lr) if fine_tune_encoder else None
    decoder = decoder.to(device)
    encoder = encoder.to(device)
    loss_criterion = nn.CrossEntropyLoss().to(device)
    normalize = transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                     std=[0.229, 0.224, 0.225])
    train_loader = torch.utils.data.DataLoader(
        CaptionDataset(data_folder, data_name, 'TRAIN', transform=transforms.Compose([normalize])),
        batch_size=batch_size, shuffle=True, num_workers=workers, pin_memory=True)
    val_loader = torch.utils.data.DataLoader(
        CaptionDataset(data_folder, data_name, 'VAL', transform=transforms.Compose([normalize])),
        batch_size=batch_size, shuffle=True, num_workers=workers, pin_memory=True)

    train(train_loader=train_loader,
          encoder=encoder,
          decoder=decoder,
          loss_criterion=loss_criterion,
          encoder_optimizer=encoder_optimizer,
          decoder_optimizer=decoder_optimizer)

    state = {'encoder': encoder,
            'decoder': decoder,
            'encoder_optimizer': encoder_optimizer,
            'decoder_optimizer': decoder_optimizer}
    filename = 'model_' + data_name + '.pth.tar'
    torch.save(state, filename)


def train(train_loader, encoder, decoder, loss_criterion, encoder_optimizer, decoder_optimizer):

    decoder.train()
    encoder.train()
    
    losses = Tracker()

    for i, (imgs, caps, caplens) in enumerate(train_loader):

        imgs = imgs.to(device)
        caps = caps.to(device)
        caplens = caplens.to(device)

        imgs = encoder(imgs)
        scores, caps_sorted, decode_lengths, alphas, sort_ind = decoder(imgs, caps, caplens)

        targets = caps_sorted[:, 1:]
        scores, _ = pack_padded_sequence(scores, decode_lengths, batch_first=True)
        targets, _ = pack_padded_sequence(targets, decode_lengths, batch_first=True)
        loss = criterion(scores, targets)
        loss += alpha_c * ((1. - alphas.sum(dim=1)) ** 2).mean()

        decoder_optimizer.zero_grad()
        if encoder_optimizer is not None:
            encoder_optimizer.zero_grad()
        loss.backward()

        if grad_clip_range is not None:
            for group in decoder_optimizer.param_groups:
              for param in group['params']:
                  if param.grad is not None:
                      param.grad.data.clamp_(-grad_clip_range, grad_clip_range)
            if encoder_optimizer is not None:
              for group in encoder_optimizer.param_groups:
                for param in group['params']:
                    if param.grad is not None:
                        param.grad.data.clamp_(-grad_clip_range, grad_clip_range)

        decoder_optimizer.step()
        if encoder_optimizer is not None:
            encoder_optimizer.step()

        losses.update(loss.item(), sum(decode_lengths))

        if i % print_freq == 0:
            print('Loss {loss.val:.4f} ({loss.avg:.4f})'.format(i, len(train_loader), loss=losses))


if __name__ == '__main__':
    main()