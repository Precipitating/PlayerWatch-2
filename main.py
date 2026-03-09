import os
import sys
BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
os.chdir(BASE_DIR)
import scrape_events


print(f'Working directory: {BASE_DIR}')

def start():
    scrape_events.start_program()

if __name__ == "__main__":
    start()

