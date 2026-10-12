"""Grant admin to one already verified account without changing its password."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pilot.auth import AccountStore, normalize_email
from pilot.admin import AdminStore

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--accounts-db',type=Path,required=True)
    parser.add_argument('--email',required=True)
    args=parser.parse_args()
    path=args.accounts_db.resolve()
    if not path.is_file() or 'public_html' in path.parts:
        parser.error('Нужна существующая приватная база аккаунтов вне public_html.')
    if not normalize_email(args.email):
        parser.error('Укажите почту подтверждённого аккаунта.')
    admin=AdminStore(AccountStore(path))
    uid=admin.grant_verified(args.email)
    print('Права администратора выданы существующему аккаунту. Пароль и прогресс сохранены.')

if __name__=='__main__':
    main()
