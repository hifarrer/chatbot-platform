#!/usr/bin/env python3
"""
Copy existing documents, avatars and knowledge bases into Bunny.net.

    RUN THIS ON THE LIVE INSTANCE, IN THE RENDER SHELL, BEFORE THE CUTOVER DEPLOY.

Render rebuilds the container filesystem from git on every deploy. The files
this script copies are on that filesystem right now and are gone the moment a
new container starts, so a copy made after deploying finds nothing to copy.

    python migrate_to_bunny.py --dry-run     # report what would move
    python migrate_to_bunny.py               # do it
    python migrate_to_bunny.py --audit       # objects in storage with no owning row

Copies only - nothing local is deleted, and an object already in the zone is
skipped unless --force. Documents are committed one row at a time, so a run that
dies partway keeps everything it already did.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REPO = os.path.dirname(os.path.abspath(__file__))


def human(n):
    return f'{n:,} bytes' if n < 1024 * 1024 else f'{n / (1024 * 1024):.1f} MB'


def already_there(storage, zone, key, size):
    info = storage.stat(zone, key)
    return bool(info and (size is None or info.get('bytes') == size))


def migrate_documents(app, storage, args):
    """Upload each document that still has no storage key."""
    from app import db, Document, resolve_document_path
    from services.object_storage import PRIVATE, document_key

    print('\n--- documents ---')
    pending = (Document.query.filter(Document.storage_key.is_(None))
               .order_by(Document.id).all())
    if not pending:
        print('  every document row already has a storage key')
        return 0, 0

    copied = missing = total_bytes = 0
    upload_folder = app.config.get('UPLOAD_FOLDER', 'uploads')

    for document in pending:
        path = resolve_document_path(document, upload_folder)
        if not path:
            missing += 1
            print(f'  MISSING  document {document.id} ({document.original_filename!r}) '
                  f'- no file at {document.file_path!r}')
            continue

        with open(path, 'rb') as handle:
            data = handle.read()
        key = document_key(document.chatbot_id, document.filename)

        if not args.force and already_there(storage, PRIVATE, key, len(data)):
            print(f'  skip     {key} (already stored)')
            if not args.dry_run:
                document.storage_key = key
                db.session.commit()
            continue

        if args.dry_run:
            print(f'  would copy {key} ({human(len(data))})')
        else:
            storage.put(PRIVATE, key, data)
            # Commit per row: a run that dies at row 400 of 500 keeps 399.
            document.storage_key = key
            db.session.commit()
            print(f'  copied   {key} ({human(len(data))})')
        copied += 1
        total_bytes += len(data)

    print(f'  {"would copy" if args.dry_run else "copied"} {copied} document(s), '
          f'{human(total_bytes)}; {missing} file(s) already missing')
    return copied, missing


def migrate_avatars(app, storage, args):
    """Upload every local avatar, and report both kinds of mismatch."""
    from app import Chatbot
    from services.object_storage import PUBLIC, avatar_key

    print('\n--- avatars ---')
    local_dir = os.environ.get('LOCAL_STORAGE_PUBLIC_DIR') or os.path.join(
        REPO, 'static', 'uploads')
    referenced = {c.avatar_filename for c in Chatbot.query.all() if c.avatar_filename}
    predefined = {'1.png', '2.png', '3.png', '4.png', '5.png', '6.png'}
    referenced -= predefined

    on_disk = set()
    if os.path.isdir(local_dir):
        on_disk = {n for n in os.listdir(local_dir)
                   if os.path.isfile(os.path.join(local_dir, n))}

    copied = total_bytes = 0
    for name in sorted(on_disk):
        path = os.path.join(local_dir, name)
        with open(path, 'rb') as handle:
            data = handle.read()
        key = avatar_key(name)
        if not args.force and already_there(storage, PUBLIC, key, len(data)):
            print(f'  skip     {key} (already stored)')
            continue
        if args.dry_run:
            print(f'  would copy {key} ({human(len(data))})')
        else:
            storage.put(PUBLIC, key, data)
            print(f'  copied   {key} ({human(len(data))})')
        copied += 1
        total_bytes += len(data)

    # Upload unreferenced files anyway: a stale object costs a fraction of a
    # cent, a missing avatar is a broken image on a customer's site.
    for name in sorted(referenced - on_disk):
        print(f'  MISSING  avatar {name!r} is referenced by a chatbot but has no local file')
    for name in sorted(on_disk - referenced):
        print(f'  note     {name!r} is on disk but referenced by no chatbot (uploaded anyway)')

    print(f'  {"would copy" if args.dry_run else "copied"} {copied} avatar(s), '
          f'{human(total_bytes)}')
    return copied


def migrate_artifacts(app, storage, args):
    """Upload every knowledge base found in the legacy training_data folder."""
    from app import Chatbot
    from services.object_storage import PRIVATE, artifact_key

    print('\n--- knowledge bases ---')
    legacy_dir = os.path.join(REPO, 'training_data')
    if not os.path.isdir(legacy_dir):
        print(f'  no legacy folder at {legacy_dir}')
        return 0

    copied = total_bytes = 0
    seen_ids = set()
    for name in sorted(os.listdir(legacy_dir)):
        if not (name.startswith('chatbot_') and name.endswith('.json')):
            continue
        try:
            chatbot_id = int(name[len('chatbot_'):-len('.json')])
        except ValueError:
            continue
        seen_ids.add(chatbot_id)
        path = os.path.join(legacy_dir, name)
        with open(path, 'rb') as handle:
            data = handle.read()
        key = artifact_key(chatbot_id)
        if not args.force and already_there(storage, PRIVATE, key, len(data)):
            print(f'  skip     {key} (already stored)')
            continue
        if args.dry_run:
            print(f'  would copy {key} ({human(len(data))})')
        else:
            storage.put(PRIVATE, key, data)
            print(f'  copied   {key} ({human(len(data))})')
        copied += 1
        total_bytes += len(data)

    trained = {c.id for c in Chatbot.query.filter_by(is_trained=True).all()}
    for chatbot_id in sorted(trained - seen_ids):
        if not storage.stat(PRIVATE, artifact_key(chatbot_id)):
            print(f'  MISSING  chatbot {chatbot_id} is marked trained but has no '
                  f'knowledge base anywhere - it needs retraining')

    print(f'  {"would copy" if args.dry_run else "copied"} {copied} knowledge base(s), '
          f'{human(total_bytes)}')
    return copied


def audit(app, storage):
    """Objects in storage that no database row owns. They cost money forever."""
    from app import Chatbot, Document
    from services.object_storage import PRIVATE, PUBLIC

    print('\n--- audit ---')
    orphans = 0

    keys = {d.storage_key for d in Document.query.all() if d.storage_key}
    for entry in storage.list(PRIVATE, 'documents/'):
        if entry['key'] not in keys:
            print(f"  orphan  {entry['key']} ({human(entry['bytes'])})")
            orphans += 1

    trained_ids = {c.id for c in Chatbot.query.all()}
    for entry in storage.list(PRIVATE, 'training/'):
        name = entry['name']
        try:
            chatbot_id = int(name[len('chatbot_'):-len('.json')])
        except ValueError:
            continue
        if chatbot_id not in trained_ids:
            print(f"  orphan  {entry['key']} (chatbot {chatbot_id} no longer exists)")
            orphans += 1

    referenced = {c.avatar_filename for c in Chatbot.query.all() if c.avatar_filename}
    for entry in storage.list(PUBLIC, 'avatars/'):
        if entry['name'] not in referenced:
            print(f"  orphan  {entry['key']} ({human(entry['bytes'])})")
            orphans += 1

    print(f'  {orphans} orphaned object(s)')
    return orphans


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='report without writing')
    parser.add_argument('--force', action='store_true', help='overwrite objects already stored')
    parser.add_argument('--only', choices=('documents', 'avatars', 'training'),
                        help='migrate a single category')
    parser.add_argument('--audit', action='store_true',
                        help='list stored objects with no owning database row')
    parser.add_argument('--allow-mismatch', action='store_true',
                        help='run even when none of the pending documents exist here')
    args = parser.parse_args()

    from app import create_app, resolve_document_path
    from services.object_storage import describe_storage, get_storage

    # Say which database this is before doing anything. .env normally points at
    # the live Postgres, so a script run from a laptop talks to production - and
    # create_app() runs db.create_all(). Print it, so nobody finds out later.
    raw_url = os.environ.get('DATABASE_URL', 'sqlite (local)')
    if '@' in raw_url:
        raw_url = raw_url.split('@', 1)[1]          # never print credentials
    print('=' * 70)
    print('DATABASE')
    print('=' * 70)
    print(f'  {raw_url}')

    flask_app = create_app()
    with flask_app.app_context():
        info = describe_storage()
        print('\n' + '=' * 70)
        print('STORAGE')
        print('=' * 70)
        print(f"  backend: {info.get('backend')}")
        for label, zone in (info.get('zones') or {}).items():
            print(f"  {label:<8} zone={zone['zone']} host={zone['host']} "
                  f"cdn={zone['cdn_url'] or 'none'} key={zone['access_key']}")

        if info.get('backend') != 'bunny':
            print('\nThe Bunny backend is not configured, so there is nothing to migrate '
                  'into. Set the BUNNY_* variables and run this again.')
            return 1

        storage = get_storage()

        if args.audit:
            audit(flask_app, storage)
            return 0

        # Wrong-machine guard. The files this script copies live on the machine
        # that served the uploads - on Render, the disk at /uploads. Run it from
        # a laptop against the live database and it finds none of them, while
        # cheerfully uploading whatever dev artifacts happen to be in the local
        # training_data folder, over the top of real chatbots' knowledge bases.
        if not args.allow_mismatch:
            from app import Document
            pending = Document.query.filter(Document.storage_key.is_(None)).all()
            resolvable = sum(
                1 for d in pending
                if resolve_document_path(d, flask_app.config.get('UPLOAD_FOLDER', 'uploads')))
            remote_db = not (os.environ.get('DATABASE_URL', '')).startswith('sqlite')
            if pending and resolvable == 0 and remote_db:
                print('\n' + '!' * 70)
                print('REFUSING TO RUN - this looks like the wrong machine.')
                print('!' * 70)
                print(f'  The database has {len(pending)} document(s) still to migrate, and')
                print('  NONE of their files exist here. They are on the machine that')
                print('  served the uploads - on Render, the disk mounted at /uploads.')
                print()
                print('  Run this in the Render Shell for that service instead.')
                print('  Continuing here would upload only whatever local dev artifacts')
                print('  happen to be lying around, over real chatbots\' knowledge bases.')
                print()
                print('  Pass --allow-mismatch if you genuinely mean to run it here.')
                return 2

        print('\n' + '=' * 70)
        print('MIGRATING' + (' (DRY RUN - nothing will be written)' if args.dry_run else ''))
        print('=' * 70)

        if args.only in (None, 'documents'):
            migrate_documents(flask_app, storage, args)
        if args.only in (None, 'avatars'):
            migrate_avatars(flask_app, storage, args)
        if args.only in (None, 'training'):
            migrate_artifacts(flask_app, storage, args)

        print()
        if args.dry_run:
            print('Dry run complete. Re-run without --dry-run to copy.')
        else:
            print('Done. These files now survive deploys. Deploy the cutover when ready.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
