#!/usr/bin/env python3
import argparse
from wsgiref.simple_server import make_server
from axiom_engine.valuation_http import app

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',default='127.0.0.1'); parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    with make_server(args.host,args.port,app) as server:
        print(f'AXIOM valuation API listening on http://{args.host}:{args.port}')
        server.serve_forever()
if __name__=='__main__': main()
