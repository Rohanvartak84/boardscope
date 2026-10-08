import argparse
import uvicorn


def main():
    parser = argparse.ArgumentParser(description='BoardScope local embedded test lab')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    uvicorn.run('boardscope.app:app', host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()
