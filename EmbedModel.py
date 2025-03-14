import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import BertTokenizer, BertConfig, BertModel,\
    RobertaTokenizer, RobertaConfig, RobertaModel,\
    DistilBertTokenizer, DistilBertConfig, DistilBertModel, \
    AlbertTokenizer, AlbertConfig, AlbertModel, \
    XLMTokenizer, XLMConfig,  XLMModel, \
    XLNetTokenizer, XLNetConfig,  XLNetModel

def _get_model(model_name):
    if model_name == 'albert':
        tokenizer = AlbertTokenizer.from_pretrained("albert/albert-base-v2")
        config = AlbertConfig.from_pretrained("albert/albert-base-v2")
        model = AlbertModel.from_pretrained("albert/albert-base-v2")
        dim = config.hidden_size
    elif model_name == 'bert':
        tokenizer = BertTokenizer.from_pretrained('bert-base-uncased', do_lower_case=True)
        config = BertConfig.from_pretrained('bert-base-uncased')
        model = BertModel.from_pretrained('bert-base-uncased', config=config)
        dim = config.hidden_size
    elif model_name == 'xlnet':
        tokenizer = XLNetTokenizer.from_pretrained("xlnet/xlnet-base-cased")
        config = XLNetConfig.from_pretrained("xlnet/xlnet-base-cased")
        model = XLNetModel.from_pretrained("xlnet/xlnet-base-cased", config=config)
        dim = config.d_model
    elif model_name == 'xlm':
        tokenizer = XLMTokenizer.from_pretrained("FacebookAI/xlm-mlm-en-2048")
        config = XLMConfig.from_pretrained("FacebookAI/xlm-mlm-en-2048")
        model = XLMModel.from_pretrained("FacebookAI/xlm-mlm-en-2048", config=config)
        dim = config.emb_dim
    elif model_name == 'roberta':
        tokenizer = RobertaTokenizer.from_pretrained("FacebookAI/roberta-base")
        config = RobertaConfig.from_pretrained("FacebookAI/roberta-base")
        model = RobertaModel.from_pretrained("FacebookAI/roberta-base")
        dim = config.hidden_size
    elif model_name == 'distilbert':
        tokenizer = DistilBertTokenizer.from_pretrained("distilbert-base-uncased")
        config = DistilBertConfig.from_pretrained("distilbert-base-uncased")
        model = DistilBertModel.from_pretrained("distilbert-base-uncased")
        dim = config.dim
    else:
        print('No known model')
        return None
    return model, tokenizer, config, dim


class EmbedModel(nn.Module):
    def __init__(self, useful_field_num, lm, device='cuda'):
        super(EmbedModel, self).__init__()

        #if not isinstance(device, list):
        #    device = [device]
        if type(device) == list:
            self.device = torch.device("cuda:{:d}".format(device[0]))
        else:
            self.device = device
        model, self.tokenizer, self.config, self.dim = _get_model(lm)
        #self.tokenizer = BertTokenizer.from_pretrained('bert-base-uncased', do_lower_case=True)
        #self.config = BertConfig.from_pretrained('bert-base-uncased')
        if lm == 'xlnet' or lm == 'xlm':
            self.max_token_length = 1000
        else:
            self.max_token_length = self.config.max_position_embeddings
        if torch.cuda.is_available() and type(device)==list:
            self.model = nn.DataParallel(model, device_ids=device)#BertModel.from_pretrained('bert-base-uncased', config=self.config), device_ids=device)
        else:
            self.model = model #BertModel.from_pretrained('bert-base-uncased', config=self.config)
        for param in self.model.parameters():
            param.requires_grad = True
        #self.dim = 768
        self.similarity_network = nn.Sequential(
            nn.Linear(2 * self.dim, self.dim),
            nn.ReLU(),
            nn.Linear(self.dim, 1)
        )


        self.field_num = useful_field_num

    def get_feature(self, sentences, center_sentence):
        """
        :param sentence
        :return: embedding
        """
        node_num = len(sentences)
        center_tokens = self.tokenizer.tokenize(center_sentence) + ["[SEP]"]
        tokens = [["[CLS]"] + self.tokenizer.tokenize(s) + ["[SEP]"] for s in sentences]
        lengths = [len(t) for t in tokens]
        center_length = len(center_tokens)
        max_len = min(max(lengths) + center_length, self.max_token_length)


        input_ids = [self.tokenizer.convert_tokens_to_ids(t + center_tokens) for t in tokens]
        segment_ids = [[0] * l + [1] * center_length for l in lengths]
        input_masks = [[1] * (l + center_length) for l in lengths]

        for i in range(node_num):
            padding_len = max_len - len(input_ids[i])
            if padding_len > 0:
                input_ids[i] += [0] * padding_len
                input_masks[i] += [0] * padding_len
                segment_ids[i] += [0] * padding_len
            elif padding_len < 0:
                token_padding = int(round(segment_ids[i].index(1) / len(segment_ids[i])*(-padding_len)))
                center_padding = -padding_len - token_padding
                if token_padding==0:
                    input_ids[i] = input_ids[i][:-center_padding]
                    input_masks[i] = input_masks[i][:-center_padding]
                    segment_ids[i] = segment_ids[i][:-center_padding]
                elif center_padding==0:
                    input_ids[i] = (input_ids[i][:segment_ids[i].index(1)][:-token_padding] +
                                    input_ids[i][segment_ids[i].index(1):])
                    input_masks[i] = (input_masks[i][:segment_ids[i].index(1)][:-token_padding] +
                                      input_masks[i][segment_ids[i].index(1):])
                    segment_ids[i] = (segment_ids[i][:segment_ids[i].index(1)][:-token_padding] +
                                      segment_ids[i][segment_ids[i].index(1):])
                else:
                    input_ids[i] = (input_ids[i][:segment_ids[i].index(1)][:-token_padding] +
                                    input_ids[i][segment_ids[i].index(1):][:-center_padding])
                    input_masks[i] = (input_masks[i][:segment_ids[i].index(1)][:-token_padding] +
                                      input_masks[i][segment_ids[i].index(1):][:-center_padding])
                    segment_ids[i] = (segment_ids[i][:segment_ids[i].index(1)][:-token_padding] +
                                      segment_ids[i][segment_ids[i].index(1):][:-center_padding])
            if 1 not in segment_ids[i] or segment_ids[i].index(1) < 5:
                print(segment_ids[i], padding_len, token_padding, center_padding)
            assert len(input_ids[i]) == max_len
            assert len(input_masks[i]) == max_len
            assert len(segment_ids[i]) == max_len


        input_ids = torch.Tensor(input_ids).cuda().long()
        segment_ids = torch.Tensor(segment_ids).cuda().long()
        input_masks = torch.Tensor(input_masks).cuda().long()

        #_ , pooled_output\
        output = self.model(input_ids=input_ids, token_type_ids=segment_ids, attention_mask=input_masks)
        pooled_output = output.pooler_output
        features = pooled_output

        return features


    def single_forward(self, example, max_node):
        attrs = []

        center_attr = " ".join(example["center"][1:])
        for node in example["neighbors"]:
            attr = node[1:]
            attrs.append(" ".join(attr))

        one_hop_nodes = len(attrs)

        features = self.get_feature(attrs, center_attr)

        num_nodes, fdim = features.shape

        N = num_nodes
        A_feat = torch.cat([features.repeat(1, N).view(N * N, -1), features.repeat(N, 1)], dim=1).view(N, -1, 2 * self.dim)
        A = self.similarity_network(A_feat).squeeze(2)
        A = F.softmax(A, dim=1)

        A_ = torch.zeros(max_node, max_node).to(self.device)
        A_[:num_nodes, :num_nodes] = A


        labels = example["labels"].copy()
        if "neighbors_mask" in example:
            mask = example["neighbors_mask"].copy()
        else:
            mask = [1] * len(example["labels"])


        assert len(labels) == one_hop_nodes, "labels len {:d} while only {:d} one_hop_nodes".format(len(labels), one_hop_nodes)

        labels += [-10] * (max_node - one_hop_nodes)
        mask += [0] * (max_node - one_hop_nodes)


        features = torch.cat([features, torch.zeros(max_node - num_nodes, fdim).to(self.device)], dim=0)

        return features, A_, labels, mask


    def forward(self, batch):
        feature = []
        A = []
        label = []
        mask = []

        max_node  = 0

        for ex in batch:
            if len(ex["neighbors"]) >  max_node:
                max_node = len(ex["neighbors"])

        for ex in batch:
            f, _A, l, m = self.single_forward(ex, max_node)
            feature.append(f)
            A.append(_A)
            label.append(l)
            mask.append(m)

        feature = torch.stack(tuple(feature), dim=0).to(self.device)
        A = torch.stack(tuple(A), dim=0).to(self.device)
        label = torch.Tensor(label).to(self.device)
        mask = torch.Tensor(mask).to(self.device)

        return feature, A, label, mask
