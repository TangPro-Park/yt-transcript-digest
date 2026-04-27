import yaml
cfg = yaml.safe_load(open('config.yaml', encoding='utf-8'))
print('filter:', cfg.get('filter', {}))
print('skip_keywords:', cfg.get('filter', {}).get('skip_keywords', []))
