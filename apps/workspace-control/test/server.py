"""Serve the real API and production UI against a disposable, synthetic workspace."""
import os
from pathlib import Path
import runpy
import sys

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE / '.agents/bin'))
from ws_web import serve

fixture = runpy.run_path(str(SOURCE / 'test/ws-web.test.py'))['WebControlReadFlow']()
fixture.setUp()
try:
    context = fixture.context
    with (context / 'registry.tsv').open('a') as registry:
        registry.write('studio\texample\t-\tprojects/example/studio\t-\tclient\t-\tDesign system and shared components\n')
        registry.write('atlas\tplatform\t-\tprojects/example/atlas\t-\tclient\t-\tA service for the next generation of tools\n')
    for project in ('studio', 'atlas'):
        (fixture.root / 'projects/example' / project).mkdir(parents=True)
    (context / 'clients/example').mkdir(parents=True)
    (context / 'clients/example/client.md').write_text('# Example Studio\nA synthetic workspace for testing.')
    (context / 'clients/platform').mkdir(parents=True)
    (context / 'clients/platform/client.md').write_text('# Platform\nA second synthetic client for filtering.')
    (context / 'runs/workspace/demo/plan.md').write_text('# Delivery plan\n\n- Validate every workflow\n- Ship an accessible control desk\n')
    (context / 'runs/workspace/demo/handoff.md').write_text('# Handoff\nContinue browser validation here.')
    # Never read the operator's personal usage source from a test process.
    with (fixture.root / 'workspace.conf').open('a') as config:
        config.write(f'usage_source = {fixture.root}/missing-usage\n')
    os.environ['WS_UIDL_DIST'] = str(SOURCE / 'apps/workspace-control/dist')
    serve(fixture.root, '127.0.0.1', 18765, token='browser-test-token')
finally:
    fixture.doCleanups()
