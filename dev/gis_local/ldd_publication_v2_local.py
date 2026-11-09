"""W5 Local operator: the A3 LDD prepare/verify/publish flow on the current ledger (027-052).

Same containers, trusted verifier, prepared store and publication provider as the A3 operator
(ldd_publication_local.py), whose proof accepts only ledger 38-40 because it predates 041-052. This subclass
accepts exactly the ledger 027..052 on both local databases, with every applied migration's SHA256 equal to the
repository file (the check gee_dashboard_local uses) and the broad activation gate closed. Nothing else changes:
no migration, no guard code, no extra worker, no Cloud, no GEE. Output: <runtime root>/w5-ldd-publication/.

  proof   read-only ledger, gate and container check.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
spec = importlib.util.spec_from_file_location('w5_existing_a3', HERE / 'ldd_publication_local.py')
a3 = importlib.util.module_from_spec(spec); sys.modules[spec.name] = a3; spec.loader.exec_module(a3)
LEDGER_TOP = 52


def ledger_problem(ledger, gate, migrations=REPO / 'green-area-backend/migrations', top=LEDGER_TOP):
    """None when the ledger is exactly 027..top with every SHA256 equal to its file and the gate closed."""
    versions = [row['version'] for row in ledger]
    if gate is not False or versions != list(range(27, top + 1)):
        return 'W5_LOCAL_TARGET_REJECTED'
    for row in ledger:
        paths = list(Path(migrations).glob(f"{row['version']:03d}_*.sql"))
        if len(paths) != 1 or hashlib.sha256(paths[0].read_bytes()).hexdigest() != row['sha256']:
            return 'APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED'
    return None


class LddPublicationV2Local(a3.LddPublicationLocal):
    def __init__(self, root):
        super().__init__(root)
        self.output = self.db.runtime.root / 'w5-ldd-publication'
        self.output.mkdir(exist_ok=True)

    def proof_a2(self):
        self.check_frozen(); self.attest()
        if a3.m.fingerprint()['branch'] != a3.m.GIS_BRANCH:
            raise RuntimeError('WRONG_BRANCH')
        for db in a3.a2.a1.DATABASES:
            self.db.proof(db, stage='gis')
            state = self.sql("SELECT jsonb_build_object('gate',(SELECT activation_enabled FROM gis.environment),"
                "'ledger',(SELECT jsonb_agg(to_jsonb(t) ORDER BY version) FROM gis.schema_migrations t))", db, read_only=True)
            problem = ledger_problem(state['ledger'], state['gate'])
            if problem:
                raise RuntimeError(problem)
        return {'local_only': True, 'broad_gate_closed': True, 'ledger_top': LEDGER_TOP, 'ledger_source_match': True,
                'databases': list(a3.a2.a1.DATABASES)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('proof',))
    parser.add_argument('--runtime-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(LddPublicationV2Local(args.runtime_dir).proof_a2()))
