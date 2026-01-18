import requests
from bs4 import BeautifulSoup
import csv
import os.path
from datetime import datetime

with open('song_data.csv', 'r') as csvfile:
    reader = csv.DictReader(csvfile)

    # Open a new CSV file for writing:
    with open('new_song_data.csv', 'w', newline='') as new_csvfile:
        fieldnames = ['title', 'artist', 'album']
        writer = csv.DictWriter(new_csvfile, fieldnames=fieldnames)
        writer.writeheader()  # Write the header row

        # Write the desired columns to the new CSV file:
        for row in reader:
            writer.writerow({'title': row['Song'], 'artist': row['Artist'], 'album': row['Album']})
