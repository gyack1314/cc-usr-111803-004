"""只读重放合成的来源交互并展示当前接收状态，或驱动本地演练页采集。"""
import argparse
import json
from .transport import Replay
from .ledger import connect,receive
from .view import overview
from .portal_workflow import collect_catalog
from .catalog import catalog as build_catalog

def main():
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest='command',required=True)

    inspect_p=sub.add_parser('inspect',help='重放冻结来源并展示账本概览')
    inspect_p.add_argument('manifest')

    collect_p=sub.add_parser('collect-catalog',help='采集本地演练页的全部门店分页')
    collect_p.add_argument('page_path')
    collect_p.add_argument('--db',default='capture-state.sqlite3')
    collect_p.add_argument('--collection',default='pork-004')
    collect_p.add_argument('--max-pages',type=int,default=None,
                           help='限制本次处理的稳定页数，用于演练中断后接续')

    view_p=sub.add_parser('catalog-view',help='查看已保存目录的当前报价与历史版本')
    view_p.add_argument('--db',default='capture-state.sqlite3')
    view_p.add_argument('--collection',default='pork-004')

    args=p.parse_args()
    if args.command=='inspect':
        replay=Replay(args.manifest)
        db=connect(':memory:')
        collection='pork-004'
        for step in replay.steps:
            request=step['request']
            raw,receipt=replay.request(request['method'],request['url'])
            receive(db,collection,raw,receipt)
        print(json.dumps(overview(db,collection),ensure_ascii=False,indent=2))
        db.close()
    elif args.command=='collect-catalog':
        db=connect(args.db)
        try:
            result=collect_catalog(db,args.collection,args.page_path,max_pages=args.max_pages)
        finally:
            db.close()
        print(json.dumps(result,ensure_ascii=False,indent=2))
    elif args.command=='catalog-view':
        db=connect(args.db)
        try:
            print(json.dumps(build_catalog(db,args.collection),ensure_ascii=False,indent=2))
        finally:
            db.close()

if __name__=='__main__':main()
