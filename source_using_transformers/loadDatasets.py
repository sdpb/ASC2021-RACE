from datasets import load_dataset
import glob


ds = load_dataset('json', data_files=glob.glob('../RACE/train/asc*****.json'), field='data')
print(ds)
