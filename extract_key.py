"""Extract DEEPSEEK_API_KEY from Hermes .env and export it."""
import os

env_path = os.path.expanduser('~/AppData/Local/hermes/.env')
with open(env_path) as f:
    for line in f:
        if line.startswith('DEEPSEEK_API_KEY='):
            val = line.strip().split('=', 1)[1]
            # Write shell script to export it
            script = f'export DEEPSEEK_API_KEY="{val}"\n'
            out_path = os.path.expanduser('~/set_key.sh')
            with open(out_path, 'w') as out:
                out.write(script)
            print(f'Key extracted (len={len(val)}): {val[:8]}...{val[-4:]}')
            print(f'Script written to {out_path}')
            break
