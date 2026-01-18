import requests
from bs4 import BeautifulSoup
import csv
import os.path
from urllib.parse import urljoin

def scrape_playlist_item(playlist_item, writer, csv_filename):
    # Extract information from the playlist item
    playlist_url = playlist_item.find('a', {'class': 'link row'})['href']
    playlist_datetime = playlist_item.find('div', {'class': 'datetime playlist'})
    playlist_date = playlist_datetime.find('span', {'class': 'month'}).text + ' ' + playlist_datetime.find('span', {'class': 'day'}).text + ' ' + playlist_datetime.find('span', {'class': 'year'}).text
    playlist_time = playlist_datetime.find('span', {'class': 'time'}).text
    show_title = playlist_item.find('h3', {'class': 'show-title'}).text.strip()

    # Check if the show category element exists
    show_category_element = playlist_item.find('p', {'class': 'show-category'})
    show_category = show_category_element.text.strip() if show_category_element else 'N/A'

    dj_name = playlist_item.find('p', {'class': 'dj-name'}).text.strip()

    # Write the playlist data to the CSV file for playlist URLs if it's not a duplicate
    if not playlist_url_exists(playlist_url, csv_filename):
        writer.writerow([playlist_url, playlist_date, playlist_time, show_title, show_category, dj_name])

        # Print or process the extracted information as needed
        print(f"Playlist URL: {playlist_url}")
        print(f"Date: {playlist_date}")
        print(f"Time: {playlist_time}")
        print(f"Show Title: {show_title}")
        print(f"Show Category: {show_category}")
        print(f"DJ Name: {dj_name}")
        print("\n")

def playlist_url_exists(playlist_url, csv_filename):
    # Check if the playlist URL is already in the CSV file
    with open(csv_filename, mode='r', newline='') as file:
        reader = csv.reader(file)
        next(reader, None)  # Skip header row
        for row in reader:
            if playlist_url == row[0]:
                return True
    return False

def scrape_playlist(url, playlist_csv_filename='playlist_urls.csv', song_csv_filename='song_data.csv'):
    # Send a GET request to the parent page URL
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')

    # Find all the playlist items on the parent page
    playlist_items = soup.find_all('div', {'class': 'list-item'})

    # Check if the CSV file for playlist URLs exists
    header_written = os.path.isfile(playlist_csv_filename)
    with open(playlist_csv_filename, mode='a', newline='') as file:
        writer = csv.writer(file)

        if not header_written:
            # If the file does not exist, write the header row
            writer.writerow(['Playlist_URL', 'Date', 'Time', 'Show_Title', 'Show_Category', 'DJ_Name'])

        for playlist_item in playlist_items:
            scrape_playlist_item(playlist_item, writer, playlist_csv_filename)

# Example usage:
parent_page_url = input("Enter the URL of the parent page: ")
scrape_playlist(parent_page_url)



def scrape_song_data(url, csv_filename='song_data.csv'):
    # Send a GET request to the URL
    response = requests.get(url)

    # Parse the HTML code using Beautiful Soup
    soup = BeautifulSoup(response.content, 'html.parser')

    # Find all the song items on the page
    song_items = soup.find_all('tr', {'class': 'spin-item'})

    # Check if the CSV file for song data exists
    header_written = os.path.isfile(csv_filename)
    with open(csv_filename, mode='a', newline='') as file:
        writer = csv.writer(file)

        if not header_written:
            # If the file does not exist, write the header row
            writer.writerow(['Artist', 'Song', 'Album', 'DateAdded'])

        # Read the existing song data to check for duplicates
        existing_song_data = set()
        if header_written:
            with open(csv_filename, mode='r', newline='') as existing_file:
                reader = csv.reader(existing_file)
                next(reader)  # Skip header row
                existing_song_data = {(row[0], row[1], row[2]) for row in reader}

        # Append the new song data to the CSV file
        for song_item in song_items:
            artist = song_item.find('span', {'class': 'artist'}).text
            song = song_item.find('span', {'class': 'song'}).text
            album = song_item.find('span', {'class': 'release'})
            date_added = datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # Current date and time

            # Check if album information is available
            album = album.text if album else 'N/A'

            # Check if the song is already in the file
            if (artist, song, album) not in existing_song_data:
                # Write the extracted information to the CSV file
                writer.writerow([artist, song, album, date_added])
                # Add the new song to the existing data set
                existing_song_data.add((artist, song, album))

    # Print a message to confirm that the CSV file for song data has been updated
    print(f"{csv_filename} file updated successfully.")

if __name__ == "__main__":
    # Example usage:
    parent_page_url = input("Enter the URL of the parent page: ")
    scrape_playlist(parent_page_url)

    # Now, use the playlist URLs from the CSV file to scrape song data
    playlist_urls_filename = 'playlist_urls.csv'
    playlist_urls = []
    with open(playlist_urls_filename, mode='r') as file:
        reader = csv.reader(file)
        next(reader)  # Skip header row
        for row in reader:
            playlist_url = row[0]  # Assuming the playlist URLs are in the first column
            playlist_urls.append(urljoin(parent_page_url, playlist_url))

    for playlist_url in playlist_urls:
        scrape_song_data(playlist_url)

