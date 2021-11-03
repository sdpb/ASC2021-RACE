#!/bin/bash
#SBATCH --job-name=run_3_epochs_transformer.out
#SBATCH --output=slurm-%x-%j.out
#SBATCH --nodes=1
#SBATCH --exclusive

#CUDA_VISIBLE_DEVICES=0 pipenv run python run_race.py  --data_dir=../RACE --vocab_file=../pretrained_model_asc/30k-clean.vocab --spm_model_file=../pretrained_model_asc/30k-clean.model --config_file=../pretrained_model_asc/config.json  --bert_model=../pretrained_model_asc/pytorch_model.bin --output_dir=asc_models --max_seq_length=320  --do_train --do_eval --do_lower_case --train_batch_size=2 --eval_batch_size=1 --learning_rate=1e-5 --num_train_epochs=1 --gradient_accumulation_steps=1 --fp16 --loss_scale=64
export CUDA_VISIBLE_DEVICES=0 
time pipenv run python run_race.py  --data_dir=../RACE --vocab_file=../pretrained_model_asc/30k-clean.vocab --spm_model_file=../pretrained_model_asc/30k-clean.model --config_file=../pretrained_model_asc/config.json  --bert_model=../pretrained_model_asc/pytorch_model.bin --output_dir=asc_models --max_seq_length=380  --do_train --do_eval --do_lower_case --train_batch_size=1 --eval_batch_size=1 --learning_rate=1e-5 --num_train_epochs=3 --gradient_accumulation_steps=1 --loss_scale=64 # --fp16
