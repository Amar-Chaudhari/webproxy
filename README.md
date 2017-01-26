# TLEN 5330 Programming Assignment 3

## Objectives
- To build a HTTP-Proxy server that is capable of accepting HTTP/1.0 and HTTP/1.1 requests

## Background
- Performance: HTTP proxies are used to prefetch data from a page, which can significantly increase Performance
- Caching:
  - HTTP response from the server can be cached locally and returned to browser if timeout has not expired.
  - Caching increased the response time an several RTTs are saved which are required to fetch data from server

### Requirments
- Python 2.7
- BeautifulSoup

## Implementation Details
### Caching HTTP response
- Only static pages and static contents should be cached. The web server returns a `cache-control` header field which specifies if a page/content should be cached or not
  - if `cache-control` is `no-cache` then do not cache the page
  - if `cache-control` is `public/private` then cache the page
- Usually the webserver also returns a `max-age` value which should be used as timeout for the cached contents

###  Handling requests
- Server creates new thread for every requests from the browser
- If the request contents `Connection: Keep-Alive` then subsiquent requests are served from the same thread
- Every request URL is hased and then the hash is checked in the Cache.
  - If there is a hit then the corresponding timeout value is checked.
  - If the timeout < currenttime then return the saved response
  - If timeout > currenttime, then send a GET request to the server with `If-None-Match: Etag`.
  - The server will response with either `200 OK` or `304 Not Modified`
    - if `304` is received then increase the timeout and send the cached contents
    - if `200 OK` is received then delete the cached contents and return False
- If the Cache returns `False` then make a GET request to the server for the contents
  - reponse returned from the server is agained checked for `cache-control` and respective actions are taken

### Links Prefetching 
- Every response from the server is checked for `Content-Type: text/html`.
  - if there is match then the page is set for prefetching
- In prefetching, All `href` links are extracted from the page.
- A GET request is sent for the links and the response is saved in Cache with key as MD5 of the URL
- If the user clicks on any of the links in current page then we should service the page from cache

### Error Handing

#### HTTP 400 Bad Request
- Server will first check for the method directive
  - if the method is not (GET,OPTIONS,HEAD,POST,PUT,DELETE,TRACE) it will return `Invalid method error`
- Server will next check the path of request file
  - if the path does not start with `/`, server will return `Invalid URL error`
- Server will next check for the `HTTP` version
  - if the verion is not `HTTP/1.1` or `HTTP/1.0`, server will return `Invalid HTTP-Verion error`

### How to run the program
#### Proxy without user specific timeout
```
python2.7 webproxy.py 10001
```
#### Proxy with user specific timeout
```
python2.7 webproxy.py 10001 120
```

### Error Testing
#### 400 Bad Requests
```
(echo -en "GET /index.html HTTP/2.1\r\nHost: localhost\r\n\n"; sleep 10) | telnet 127.0.0.1 10001
(echo -en "GRT /index.html HTTP/1.1\r\nHost: localhost\r\n\n"; sleep 10) | telnet 127.0.0.1 10001
(echo -en "GET /index.html HTTP/1.1\r\nHost: localhost\r\n\n"; sleep 10) | telnet 127.0.0.1 10001
```
