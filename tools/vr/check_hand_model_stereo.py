#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compare actual native two-eye and multiview held-model color/depth.

Run in software_xr_lab.py with one private Monado service. Sequential native
multiplayer sessions compare world/model color and depth exactly. The SPS run
also requires a same-frame native reference with byte-identical frozen inputs;
cross-session matrix equality is diagnostic because input rounding can vary.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

import numpy as np
from PIL import Image


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('binary','client-binary','grp','model-root','work-dir'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--case',choices=('base','roll','fog','asymmetric','translucent'),default='base')
    p.add_argument('--display',default=':105')
    p.add_argument('--remote-port',type=int,default=49777)
    p.add_argument('--vertex-mode',choices=('arrays','immediate'),default='arrays')
    p.add_argument('--model-file',type=Path)
    p.add_argument('--fault',choices=('collect-right','surface-1','skin-last','replay-before','mask-retry'))
    a=p.parse_args();root=a.work_dir.resolve();root.mkdir(parents=True,exist_ok=True)
    results={};checks={};details={};error=None
    try:
        for mode in ('native','sps'):
            work=root/mode;work.mkdir()
            args=[sys.executable,str(Path(__file__).with_name('smoke_hand_model.py')),
                '--display',a.display,'--remote-port',str(a.remote_port),'--case',a.case,'--model-mode',mode,'--vertex-mode',a.vertex_mode]
            if a.model_file:args+=['--model-file',str(a.model_file.resolve())]
            if a.fault and mode=='sps':args+=['--fault',a.fault]
            for name in ('binary','client-binary','grp','model-root'):
                args+=['--'+name,str(getattr(a,name.replace('-','_')).resolve())]
            args+=['--work-dir',str(work)]
            with (work/'runner.log').open('w') as log:
                completed=subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,timeout=50)
            files=list(work.glob('hand-model-*/result.json'))
            if len(files)!=1:raise RuntimeError(f'{mode}: expected one case result')
            results[mode]=json.loads(files[0].read_text())
            if completed.returncode or not results[mode]['passed']:
                raise RuntimeError(f'{mode} case failed; inspect its owned result')
        paths={mode:Path(result['evidence_directory'])/'client' for mode,result in results.items()}
        def matrices(path):
            return re.findall(r'OpenXR hand model (?:matrix|projection):[^\n]+',(path/'client.log').read_text())
        # Separate real sessions can differ in a controller's last float bits.
        # The authoritative color/depth oracle uses a same-frame native draw
        # on copied array layers and byte-identical frozen transform inputs.
        details['cross_session_model_matrices_identical']=matrices(paths['native'])==matrices(paths['sps'])
        checks['matching_same_frame_native_inputs']=results['sps']['checks']['same_frame_native_inputs_identical']
        for eye in ('left','right'):
            for prefix in ('model-before','model-after','world'):
                name=f'{prefix}-{eye}'
                native=paths['native']/(name+'.ppm');sps=paths['sps']/(name+'.ppm')
                checks[name+'_color_exact']=native.read_bytes()==sps.read_bytes()
                checks[name+'_depth_exact']=(paths['native']/(name+'-depth.bin')).read_bytes()==(paths['sps']/(name+'-depth.bin')).read_bytes()
                delta=np.abs(np.array(Image.open(native)).astype(int)-np.array(Image.open(sps)).astype(int))
                details[name]={'changed_pixels':int(np.count_nonzero(np.any(delta!=0,axis=2))),'maximum_channel_error':int(delta.max())}
        checks['actual_cases_independently_pass']=all(r['passed'] for r in results.values())
    except Exception as exc:error=str(exc)
    result={'passed':error is None and all(checks.values()),'case':a.case,'checks':checks,'pixel_deltas':details,'runs':results,'error':error}
    (root/'hand-model-stereo.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'passed':result['passed'],'case':a.case,'checks':checks,'pixel_deltas':details,'error':error},indent=2))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
