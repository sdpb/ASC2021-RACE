# coding=utf-8
# Copyright 2018 The Google AI Language Team Authors and The HugginFace Inc. team.
# Copyright (c) 2018, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""BERT finetuning runner."""

import logging
import os
import argparse
import random
from tqdm import tqdm
import glob
import json
import time
import numpy as np
import torch
from torch.utils.data import TensorDataset, DataLoader, RandomSampler, SequentialSampler, Dataset
import torch.distributed as dist
from accelerate import Accelerator


# WHEN USING ASC ORIGINAL VERSION
# from pytorch_pretrained_bert.utils import is_main_process
# from pytorch_pretrained_bert import tokenization_albert
# from pytorch_pretrained_bert.modeling_albert import AlbertForMultipleChoice, AlbertConfig

# USING TRANSFORMERS
from transformers import AlbertForMultipleChoice, AlbertTokenizerFast, AlbertConfig, AdamW, get_linear_schedule_with_warmup, default_data_collator

from tensorboardX import SummaryWriter

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s -   %(message)s",
    datefmt="%m/%d/%Y %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def get_rank():
    if not dist.is_available():
        return 0
    if not dist.is_initialized():
        return 0
    return dist.get_rank()


def is_main_process():
    return get_rank() == 0


class RaceExample(object):
    """A single training/test example for the RACE dataset."""

    """
    For RACE dataset:
    race_id: data id
    context_sentence: article
    start_ending: question
    ending_0/1/2/3: option_0/1/2/3
    label: true answer
    """

    def __init__(
        self,
        race_id,
        context_sentence,
        start_ending,
        ending_0,
        ending_1,
        ending_2,
        ending_3,
        label=None,
    ):
        self.race_id = race_id
        self.context_sentence = context_sentence
        self.start_ending = start_ending
        self.endings = [
            ending_0,
            ending_1,
            ending_2,
            ending_3,
        ]
        self.label = label

    def __str__(self):
        return self.__repr__()

    def __repr__(self):
        l = [
            f"id: {self.race_id}",
            f"article: {self.context_sentence}",
            f"question: {self.start_ending}",
            f"option_0: {self.endings[0]}",
            f"option_1: {self.endings[1]}",
            f"option_2: {self.endings[2]}",
            f"option_3: {self.endings[3]}",
        ]

        if self.label is not None:
            l.append(f"label: {self.label}")

        return ", ".join(l)


class InputFeatures(object):
    def __init__(self, example_id, batch, label):
        self.example_id = example_id
        self.batch = batch
        self.label = label


## paths is a list containing all paths
def read_race_examples(paths):
    examples = []
    for path in paths:
        filenames = glob.glob(path + "/*json")
        for filename in filenames[:1]:
            with open(filename, "r", encoding="utf-8") as fpr:
                data_raw = json.load(fpr)
                article = data_raw["article"]
                ## for each qn
                for i in range(len(data_raw["answers"])):
                    truth = ord(data_raw["answers"][i]) - ord("A")
                    question = data_raw["questions"][i]
                    options = data_raw["options"][i]
                    examples.append(
                        RaceExample(
                            race_id=filename + "-" + str(i),
                            context_sentence=article,
                            start_ending=question,
                            ending_0=options[0],
                            ending_1=options[1],
                            ending_2=options[2],
                            ending_3=options[3],
                            label=truth,
                        )
                    )

    return examples


### paths is a list containing all paths
#def read_race_example(filename):
#    example = []
#    with open(filename, "r", encoding="utf-8") as fpr:
#        data_raw = json.load(fpr)
#        article = data_raw["article"]
#        ## for each qn
#        for i in range(len(data_raw["answers"])):
#            truth = ord(data_raw["answers"][i]) - ord("A")
#            question = data_raw["questions"][i]
#            options = data_raw["options"][i]
#            example.append(
#                RaceExample(
#                    race_id=filename + "-" + str(i),
#                    context_sentence=article,
#                    start_ending=question,
#                    ending_0=options[0],
#                    ending_1=options[1],
#                    ending_2=options[2],
#                    ending_3=options[3],
#                    label=truth,
#                )
#            )
#
#    return example


def convert_examples_to_features(examples, tokenizer, max_seq_length, is_training):
    """Loads a data file into a list of `InputBatch`s."""

    # RACE is a multiple choice task. To perform this task using Bert,
    # we will use the formatting proposed in "Improving Language
    # Understanding by Generative Pre-Training" and suggested by
    # @jacobdevlin-google in this issue
    # https://github.com/google-research/bert/issues/38.
    #
    # The input will be like:
    # [CLS] Article [SEP] Question + Option [SEP]
    # for each option
    #
    # The model will output a single value for each input. To get the
    # final decision of the model, we will run a softmax over these 4
    # outputs.
    features = []
    examples_iter = tqdm(examples, disable=False) if is_main_process() else examples
    for example_index, example in enumerate(examples_iter):
        context_tokens = example.context_sentence # tokenizer.tokenize(example.context_sentence)
        start_ending_tokens = example.start_ending # tokenizer.tokenize(example.start_ending)

        for ending_index, ending in enumerate(example.endings):
            # We create a copy of the context tokens in order to be
            # able to shrink it according to ending_tokens
            context_tokens_choice = context_tokens[:]
            ending_tokens = start_ending_tokens + " " + ending # tokenizer.tokenize(ending)

            # Modifies `context_tokens_choice` and `ending_tokens` in
            # place so that the total length is less than the
            # specified length.  Account for [CLS], [SEP], [SEP] with
            # "- 3"


            feature = tokenizer(context_tokens_choice, ending_tokens, return_tensors="pt", padding='max_length', truncation=True, max_length=max_seq_length)
            label = example.label
            #feature["labels"] = torch.tensor(label).unsqueeze(0)
   
            """
            _truncate_seq_pair(context_tokens_choice, ending_tokens, max_seq_length - 3)

            tokens = (
                ["[CLS]"]
                + context_tokens_choice
                + ["[SEP]"]
                + ending_tokens
                + ["[SEP]"]
            )
            segment_ids = [0] * (len(context_tokens_choice) + 2) +\
                [1] * (len(ending_tokens) + 1)

            input_ids = tokenizer.convert_tokens_to_ids(tokens)
            input_mask = [1] * len(input_ids)

            # Zero-pad up to the sequence length.
            padding = [0] * (max_seq_length - len(input_ids))
            input_ids += padding
            input_mask += padding
            segment_ids += padding

            assert len(input_ids) == max_seq_length
            assert len(input_mask) == max_seq_length
            assert len(segment_ids) == max_seq_length

            """

        features.append(
            InputFeatures(
                example_id=example.race_id,
                batch=feature,
                label=label,
            )
        )

    return features


def _truncate_seq_pair(tokens_a, tokens_b, max_length):
    """Truncates a sequence pair in place to the maximum length."""

    # This is a simple heuristic which will always truncate the longer sequence
    # one token at a time. This makes more sense than truncating an equal percent
    # of tokens from each, since if one sequence is very short then each token
    # that's truncated likely contains more information than a longer sequence.
    while True:
        total_length = len(tokens_a) + len(tokens_b)
        if total_length <= max_length:
            break
        if len(tokens_a) > len(tokens_b):
            tokens_a.pop()
        else:
            tokens_b.pop()



def accuracy(out, labels):
    outputs = np.argmax(out, axis=1)
    return np.sum(outputs == labels)


def select_field(features, field):
    return [
        [choice[field] for choice in feature.batch] for feature in features
    ]


def warmup_linear(x, warmup=0.002):
    if x < warmup:
        return x / warmup
    return 1.0 - x


def PRINT_DEBUG(var, exit=True):
    print(f"DEBUG::: -- TYPE: {type(var)} -- DATA: {var}\nEXITING...")
    if exit:
        exit()


class dataVISA(Dataset):
    def __init__(self, batches, labels): # batches and labels are a list
        self.batches = batches
        self.labels = labels
        assert len(self.labels) == len(self.batches)

    def __len__(self):
        return len(self.batches)

    def __getitem__(self, idx):
        return self.batches[idx], self.labels[idx]

def main():
    ete_start = time.time()
    parser = argparse.ArgumentParser()

    ## Required parameters
    parser.add_argument(
        "--data_dir",
        default=None,
        type=str,
        required=True,
        help="The input data dir. Should contain the .csv files (or other data files) for the task.",
    )
    parser.add_argument(
        "--vocab_file", default=None, type=str, required=True, help="vocab_file path"
    )
    parser.add_argument(
        "--spm_model_file",
        default=None,
        type=str,
        required=True,
        help="spm_model_file path",
    )
    parser.add_argument(
        "--config_file", default=None, type=str, required=True, help="config_file path"
    )
    parser.add_argument(
        "--bert_model",
        default=None,
        type=str,
        required=True,
        help="Bert pre-trained model selected in the list: bert-base-uncased, "
        "bert-large-uncased, bert-base-cased, bert-base-multilingual, bert-base-chinese.",
    )
    parser.add_argument(
        "--output_dir",
        default=None,
        type=str,
        required=True,
        help="The output directory where the model checkpoints will be written.",
    )

    ## Other parameters
    parser.add_argument(
        "--max_seq_length",
        default=128,
        type=int,
        help="The maximum total input sequence length after WordPiece tokenization. \n"
        "Sequences longer than this will be truncated, and sequences shorter \n"
        "than this will be padded.",
    )
    parser.add_argument(
        "--do_train",
        default=False,
        action="store_true",
        help="Whether to run training.",
    )
    parser.add_argument(
        "--do_eval",
        default=False,
        action="store_true",
        help="Whether to run eval on the dev set.",
    )
    parser.add_argument(
        "--do_lower_case",
        default=False,
        action="store_true",
        help="Set this flag if you are using an uncased model.",
    )
    parser.add_argument(
        "--train_batch_size",
        default=32,
        type=int,
        help="Total batch size for training.",
    )
    parser.add_argument(
        "--eval_batch_size", default=8, type=int, help="Total batch size for eval."
    )
    parser.add_argument(
        "--learning_rate",
        default=5e-5,
        type=float,
        help="The initial learning rate for Adam.",
    )
    parser.add_argument(
        "--num_train_epochs",
        default=3.0,
        type=float,
        help="Total number of training epochs to perform.",
    )
    parser.add_argument(
        "--warmup_proportion",
        default=0.1,
        type=float,
        help="Proportion of training to perform linear learning rate warmup for. "
        "E.g., 0.1 = 10%% of training.",
    )
    parser.add_argument(
        "--no_cuda",
        default=False,
        action="store_true",
        help="Whether not to use CUDA when available",
    )
    parser.add_argument(
        "--local_rank",
        type=int,
        default=-1,
        help="local_rank for distributed training on gpus",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="random seed for initialization"
    )
    parser.add_argument(
        "--gradient_accumulation_steps",
        type=int,
        default=1,
        help="Number of updates steps to accumulate before performing a backward/update pass.",
    )
    parser.add_argument(
        "--fp16",
        default=False,
        action="store_true",
        help="Whether to use 16-bit float precision instead of 32-bit",
    )
    parser.add_argument(
        "--loss_scale",
        type=float,
        default=0,
        help="Loss scaling to improve fp16 numeric stability. Only used when fp16 set to True.\n"
        "0 (default value): dynamic loss scaling.\n"
        "Positive power of 2: static loss scaling value.\n",
    )

    args = parser.parse_args()

    accelerator = Accelerator(device_placement=True)
    n_gpu = 1
    # INICIALMENTE SE ENTRA A ESTE IF:
    #if args.local_rank == -1 or args.no_cuda:
    #    device = torch.device(
    #        "cuda" if torch.cuda.is_available() and not args.no_cuda else "cpu"
    #    )
    #    n_gpu = torch.cuda.device_count()
    #else:
    #    torch.cuda.set_device(args.local_rank)
    #    device = torch.device("cuda", args.local_rank)
    #    n_gpu = 1
    #    # Initializes the distributed backend which will take care of sychronizing nodes/GPUs
    #    torch.distributed.init_process_group(backend="nccl")

    #if is_main_process():
    #    logger.info(
    #        "device: {} n_gpu: {}, distributed training: {}, 16-bits training: {}".format(
    #            device, n_gpu, bool(args.local_rank != -1), args.fp16
    #        )
    #    )

    if args.gradient_accumulation_steps < 1:
        raise ValueError(
            "Invalid gradient_accumulation_steps parameter: {}, should be >= 1".format(
                args.gradient_accumulation_steps
            )
        )

    # Esta operación se repite en línea 481. Se debe repetir?
    args.train_batch_size = int(
        args.train_batch_size / args.gradient_accumulation_steps
    )

    # TRYING TO SOLVE RuntimeError: CUDA error: device-side assert triggered:
    #random.seed(args.seed)
    #np.random.seed(args.seed)
    #torch.manual_seed(args.seed)
    #if n_gpu > 0:
    #    torch.cuda.manual_seed_all(args.seed)

    if not args.do_train and not args.do_eval:
        raise ValueError("At least one of `do_train` or `do_eval` must be True.")

    os.makedirs(args.output_dir, exist_ok=True)

    # With version ASC original
    ## tokenizer = tokenization_albert.FullTokenizer(args.vocab_file, do_lower_case=args.do_lower_case, spm_model_file=args.spm_model_file)
    # With version using transformers:
    tokenizer = AlbertTokenizerFast(
        args.spm_model_file, do_lower_case=args.do_lower_case
    )
    def collate_fn(examples):
        return tokenizer.pad(examples, padding="longest", return_tensors="pt")


    train_examples = None
    num_train_steps = None
    if args.do_train:
        train_dir = os.path.join(args.data_dir, "train")
        train_examples = read_race_examples([train_dir])

        # La segunda división ya se hizo en 453. Se debe repetir?
        num_train_steps = int(
            len(train_examples)
            / args.train_batch_size
            / args.gradient_accumulation_steps
            * args.num_train_epochs
        )
        print(
            len(train_examples),
            args.train_batch_size,
            args.gradient_accumulation_steps,
            args.num_train_epochs,
        )

    config = AlbertConfig.from_pretrained(args.config_file, num_labels=4)
    model = AlbertForMultipleChoice.from_pretrained(args.bert_model, config=config)

    ############## CONGELACIÓN:
    #    for name, param in model.named_parameters():
    #        if 'classifier' not in name:  # classifier layer
    #            param.requires_grad = False

    model.to(accelerator.device)
    
    # Prepare optimizer
    param_optimizer = list(model.named_parameters())

    param_optimizer = [n for n in param_optimizer if "pooler" not in n[0]]

    no_decay = ["bias", "LayerNorm.bias", "LayerNorm.weight"]
    optimizer_grouped_parameters = [
        {
            "params": [
                p for n, p in param_optimizer if not any(nd in n for nd in no_decay)
            ],
            "weight_decay": 0.01,
        },
        {
            "params": [
                p for n, p in param_optimizer if any(nd in n for nd in no_decay)
            ],
            "weight_decay": 0.0,
        },
    ]
    t_total = num_train_steps
    if args.local_rank != -1:
        t_total = t_total // torch.distributed.get_world_size()
    if args.fp16:

        try:
            from apex.optimizers import FusedAdam
            from apex import amp
        except ImportError:
            raise ImportError(
                "Please install apex from https://www.github.com/nvidia/apex to use distributed and fp16 training."
            )

        optimizer = FusedAdam(
            optimizer_grouped_parameters, lr=args.learning_rate, bias_correction=False
        )
        model, optimizer = amp.initialize(
            model,
            optimizers=optimizer,
            opt_level="O2",
            keep_batchnorm_fp32=False,
            loss_scale="dynamic" if args.loss_scale == 0 else args.loss_scale,
        )
    else:
        optimizer = AdamW(params=optimizer_grouped_parameters, lr=args.learning_rate, correct_bias=True)
        '''
        optimizer = BertAdam(
            optimizer_grouped_parameters,
            lr=args.learning_rate,
            warmup=args.warmup_proportion,
            t_total=t_total,
        )
        '''



    global_step = 0
    train_start = time.time()
    writer = SummaryWriter(os.path.join(args.output_dir, "asc"))
    if args.do_train:
        train_features = convert_examples_to_features(
            train_examples, tokenizer, args.max_seq_length, True
        )
        if is_main_process():
            logger.info("***** Running training *****")
            logger.info("  Num examples = %d", len(train_examples))
            logger.info("  Batch size = %d", args.train_batch_size)
            logger.info("  Num steps = %d", num_train_steps)
        
        #all_batches = [b.batch for b in train_features]
        #PRINT_DEBUG(all_batches[0])
        #train_data = TensorDataset(torch.tensor(**all_batches), torch.tensor([b.label for b in train_features]))
        all_batches = [b.batch for b in train_features]
        train_data = dataVISA(all_batches, [b.label for b in train_features])
        train_dataloader = DataLoader(
            train_data, shuffle=False, batch_size=args.train_batch_size, #collate_fn=collate_fn
        )

        model, optimizer, train_dataloader = accelerator.prepare(model, optimizer, train_dataloader)

        # Instantiate learning rate scheduler after preparing the training dataloader as the prepare method
        # may change its length.
        lr_scheduler = get_linear_schedule_with_warmup(
            optimizer=optimizer,
            num_warmup_steps=100,
            num_training_steps=len(train_dataloader) * int(args.num_train_epochs),
        )

        model.train()
        for ep in range(int(args.num_train_epochs)):
            tr_loss = 0
            nb_tr_examples, nb_tr_steps = 0, 0
            #train_iter = (
            #    tqdm(train_dataloader, disable=False)
            #    if is_main_process()
            #    else train_dataloader
            #)
            #if is_main_process():
            #    train_iter.set_description(
            #        "Trianing Epoch: {}/{}".format(ep + 1, int(args.num_train_epochs))
            #    )
            for index, batch in enumerate(train_dataloader):
                # PRINT_DEBUG(batch)
                #batch = dict(t.to(device) for t in batch)
                #input_ids, input_mask, segment_ids, label_ids = batch
                #outputs = model(input_ids, input_mask, segment_ids, labels=label_ids)
                #loss = outputs["loss"]
                #if n_gpu > 1:
                #    loss = loss.mean()  # mean() to average on multi-gpu.
                #if args.gradient_accumulation_steps > 1:
                #    loss = loss / args.gradient_accumulation_steps
                #tr_loss += loss.item()
                #nb_tr_examples += input_ids.size(0)
                #nb_tr_steps += 1

                # We could avoid this line since we set the accelerator with `device_placement=True`.
                #print(f"TYPE:{type(batch)} -- BATCH:{batch}")
                # batch.to(accelerator.device)

                # outputs = model(**{k: v.unsqueeze(0) for k,v in batch.items()})
                PRINT_DEBUG(batch, False)
                batch = batch[0]
                outputs = model(**batch)
                loss = outputs.logits
                loss = loss / args.gradient_accumulation_steps

                if args.fp16:
                    with amp.scale_loss(loss, optimizer) as scaled_loss:
                        #scaled_loss.backward()
                        accelerator.backward(scaled_loss)
                else:
                    #exit()
                    #loss.backward()
                    accelerator.backward(loss)

                if (index+1) % args.gradient_accumulation_steps == 0:
                    optimizer.step()
                    lr_scheduler.step()
                    optimizer.zero_grad()
                    global_step += 1

               # if is_main_process():
               #     train_iter.set_postfix(loss=loss.item())
                writer.add_scalar("loss", loss.item(), global_step=global_step)

    finish_time = time.time()
    writer.close()
    # Save a trained model
    if is_main_process():
        logger.info(
            "ete_time: {}, training_time: {}".format(
                finish_time - ete_start, finish_time - train_start
            )
        )
        model_to_save = (
            model.module if hasattr(model, "module") else model
        )  # Only save the model it-self
        output_model_file = os.path.join(args.output_dir, "pytorch_model.bin")
        torch.save(model_to_save.state_dict(), output_model_file)
        ## evaluate on dev set
    if is_main_process():
        dev_dir = os.path.join(args.data_dir, "dev")
        dev_set = [dev_dir]

        eval_examples = read_race_examples(dev_set)
        eval_features = convert_examples_to_features(
            eval_examples, tokenizer, args.max_seq_length, True
        )
        logger.info("***** Running evaluation: Dev *****")
        logger.info("  Num examples = %d", len(eval_examples))
        logger.info("  Batch size = %d", args.eval_batch_size)
        
        # Run prediction for full data
        eval_sampler = SequentialSampler(eval_data)
        eval_dataloader = DataLoader(
            [b.batch for b in eval_features], sampler=eval_sampler, batch_size=args.eval_batch_size
        )

        eval_iter = (
            tqdm(eval_dataloader, disable=False)
            if is_main_process()
            else eval_dataloader
        )
        model.eval()
        eval_loss, eval_accuracy = 0, 0
        nb_eval_steps, nb_eval_examples = 0, 0
        for step, batch in enumerate(eval_iter):
        #batch = tuple(t.to(device) for t in batch)
            #input_ids, input_mask, segment_ids, label_ids = batch
            batch.to(accelerator.device)
            with torch.no_grad():
                outputs = model(**batch)
                tmp_eval_loss = outputs.logits.argmax(dim = -1)
                PRINT_DEBUG(tmp_eval_loss)
                outputs = model(batch["input_ids"], batch["input_mask"], batch["segment_ids"])
                logits = outputs.logits

            logits = logits.detach().cpu().numpy()
            label_ids = label_ids.to("cpu").numpy()
            tmp_eval_accuracy = accuracy(logits, label_ids)

            eval_loss += tmp_eval_loss.mean().item()
            eval_accuracy += tmp_eval_accuracy

            nb_eval_examples += input_ids.size(0)
            nb_eval_steps += 1

        eval_loss = eval_loss / nb_eval_steps
        eval_accuracy = eval_accuracy / nb_eval_examples

        result = {
            "dev_eval_loss": eval_loss,
            "dev_eval_accuracy": eval_accuracy,
            "loss": eval_loss / nb_eval_steps,
        }

        logger.info("***** Dev results *****")
        for key in sorted(result.keys()):
            logger.info("  %s = %s", key, str(result[key]))


if __name__ == "__main__":
    main()
