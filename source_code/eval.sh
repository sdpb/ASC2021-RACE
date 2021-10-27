time pipenv run python test_race.py \
	--data_dir=../RACE \
	--vocab_file=../pretrained_model_asc/30k-clean.vocab \
	--spm_model_file=../pretrained_model_asc/30k-clean.model \
	--config_file=../pretrained_model_asc/config.json \
	--pretrained_model=../pretrained_model_asc/pytorch_model.bin \
	--output_dir=results \
	--max_seq_length=512 \
	--do_lower_case
