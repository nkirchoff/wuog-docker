import requests
from bs4 import BeautifulSoup
import csv
import os
from datetime import datetime
from urllib.parse import urljoin
import logging
import concurrent.futures

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def scrape_playlist(url, playlist_csv_filename='playlist_urls.csv'):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        playlist_items = soup.find_all('div', {'class': 'list-item'})

        prepare_csv(playlist_csv_filename, ['Playlist_URL', 'Date', 'Time', 'Show_Title', 'Show_Category', 'DJ_Name'])

        for playlist_item in playlist_items:
            playlist_url = playlist_item.find('a', {'class': 'link row'})['href']
            playlist_datetime = playlist_item.find('div', {'class': 'datetime playlist'})
            playlist_date = f"{playlist_datetime.find('span', {'class': 'month'}).text} {playlist_datetime.find('span', {'class': 'day'}).text} {playlist_datetime.find('span', {'class': 'year'}).text}"
            playlist_time = playlist_datetime.find('span', {'class': 'time'}).text
            show_title = playlist_item.find('h3', {'class': 'show-title'}).text.strip()
            show_category = playlist_item.find('p', {'class': 'show-category'})
            show_category = show_category.text.strip() if show_category else 'N/A'
            dj_name = playlist_item.find('p', {'class': 'dj-name'}).text.strip()

            if not is_playlist_url_duplicate(playlist_url, playlist_csv_filename) and is_valid_playlist_time(playlist_time):
                with open(playlist_csv_filename, mode='a', newline='') as file:
                    writer = csv.writer(file)
                    writer.writerow([playlist_url, playlist_date, playlist_time, show_title, show_category, dj_name])

                logging.info(f"Scraped Playlist: {playlist_url} | {playlist_date} | {playlist_time} | {show_title} | {show_category} | {dj_name}")

    except requests.RequestException as e:
        logging.error(f"Error fetching playlist page: {e}")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")

def is_valid_playlist_time(playlist_time):
    try:
        playlist_time_obj = datetime.strptime(playlist_time, '%I:%M %p')
        return datetime.strptime('1:00 AM', '%I:%M %p') <= playlist_time_obj <= datetime.strptime('5:00 AM', '%I:%M %p')
    except ValueError:
        return False

def is_playlist_url_duplicate(playlist_url, playlist_csv_filename):
    if os.path.isfile(playlist_csv_filename):
        with open(playlist_csv_filename, mode='r', newline='') as file:
            reader = csv.reader(file)
            for row in reader:
                if row and row[0] == playlist_url:
                    return True
    return False

def prepare_csv(csv_filename, header):
    if not os.path.isfile(csv_filename):
        with open(csv_filename, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(header)

def scrape_song_data(url, csv_filename='song_data.csv'):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        song_items = soup.find_all('tr', {'class': 'spin-item'})
        prepare_csv(csv_filename, ['Artist', 'Song', 'Album', 'DateAdded'])

        existing_song_data = read_existing_data(csv_filename)

        with open(csv_filename, mode='a', newline='') as file:
            writer = csv.writer(file)
            for song_item in song_items:
                artist = song_item.find('span', {'class': 'artist'}).text
                song = song_item.find('span', {'class': 'song'}).text
                album = song_item.find('span', {'class': 'release'})
                date_added = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                album = album.text if album else 'N/A'

                if (artist, song, album) not in existing_song_data:
                    writer.writerow([artist, song, album, date_added])
                    existing_song_data[(artist, song, album)] = date_added

        logging.info(f"Scraped songs from {url}")

    except requests.RequestException as e:
        logging.error(f"Error fetching song page: {e}")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")

def read_existing_data(csv_filename):
    existing_song_data = {}
    if os.path.isfile(csv_filename):
        with open(csv_filename, mode='r', newline='') as file:
            reader = csv.reader(file)
            next(reader, None)
            for row in reader:
                if row:
                    existing_song_data[(row[0], row[1], row[2])] = row[3]
    return existing_song_data

def main():
    parent_page_url = "https://spinitron.com/WUOG/dj/132321/Automation"
    scrape_playlist(parent_page_url)

    playlist_urls_filename = 'playlist_urls.csv'
    playlist_urls = []
    if os.path.isfile(playlist_urls_filename):
        with open(playlist_urls_filename, mode='r') as file:
            reader = csv.reader(file)
            next(reader, None)
            for row in reader:
                playlist_url = row[0]
                playlist_urls.append(urljoin(parent_page_url, playlist_url))

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        executor.map(scrape_song_data, playlist_urls)

if __name__ == "__main__":
    main()
