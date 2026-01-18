import asyncio
import csv
import datetime
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup

def is_valid_playlist_time(playlist_time):
    """Checks if the playlist time is within the valid range."""
    try:
        playlist_time_obj = datetime.datetime.strptime(playlist_time, '%I:%M %p')
        valid_start_time = datetime.datetime.strptime('1:00 AM', '%I:%M %p')
        valid_end_time = datetime.datetime.strptime('5:00 AM', '%I:%M %p')
        return valid_start_time <= playlist_time_obj <= valid_end_time
    except ValueError:
        return False

async def scrape_playlist(url, playlist_csv_filename, song_csv_filename):
    """Scrapes playlist data from a URL."""
    async with aiohttp.ClientSession() as session:
        response = await session.get(url)
        soup = BeautifulSoup(await response.read(), 'html.parser')

        for playlist_item in soup.find_all('div', {'class': 'list-item'}):
            playlist_url = urljoin(url, playlist_item.find('a')['href'])
            playlist_time = playlist_item.find('span', {'class': 'time'}).text
            if is_valid_playlist_time(playlist_time):
                await process_playlist(session, playlist_url, playlist_csv_filename, song_csv_filename)


async def process_playlist(session, playlist_url, playlist_csv_filename, song_csv_filename):
    """Processes a playlist and extracts song data."""
    response = await session.get(playlist_url)
    soup = BeautifulSoup(await response.read(), 'html.parser')

    for song_item in soup.find_all('tr', {'class': 'spin-item'}):
        artist = song_item.find('span', {'class': 'artist'}).text
        song = song_item.find('span', {'class': 'song'}).text
        album = song_item.find('span', {'class': 'release'})
        if album:
            album = album.text
        else:
            album = 'N/A'

        await write_song_data(song_csv_filename, artist, song, album)


async def write_song_data(filename, artist, song, album):
    """Writes song data to a CSV file."""
    with open(filename, 'a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([artist, song, album, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')])


async def main(parent_page_url, playlist_csv_filename, song_csv_filename):
    """Main function."""
    tasks = [scrape_playlist(parent_page_url, playlist_csv_filename, song_csv_filename)]

    # Scrape playlists concurrently
    await asyncio.gather(*tasks)

    print(f"{song_csv_filename} file updated successfully.")


if __name__ == "__main__":
    parent_page_url = "https://spinitron.com/WUOG/dj/132321/Automation"
    playlist_csv_filename = "new_playlist_urls.csv"
    song_csv_filename = "new_song_data.csv"

    asyncio.run(main(parent_page_url, playlist_csv_filename, song_csv_filename))

