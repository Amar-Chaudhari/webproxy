import hashlib
import re
import socket
import sys
import threading
import time

from bs4 import BeautifulSoup

# Class to cache pages and url
# When timeout > current time
#   GetUpdate function sends etag value to server.
#       if server replies with 304 not modified -> content has not changed hence refresh timeout
class ProxyCache():
    def __init__(self,timeout=120):
        self.cache = {}
        self.timeout = float(timeout)

    def set(self, key, value, etag, host, path, timeout=False):
        lock = threading.RLock()
        with lock:
            if not timeout:
                timeout = time.time() + self.timeout
            else:
                timeout = time.time() + timeout
            temp = {}
            temp['value'] = value
            temp['timeout'] = timeout
            temp['Etag'] = etag
            temp['host'] = host
            temp['path'] = path
            self.cache[key] = temp

    def get(self, key, timeout=False):
        lock = threading.RLock()
        with lock:
            if not timeout:
                timeout = time.time() + self.timeout
            else:
                timeout = time.time() + timeout

            data = self.cache.get(key)
            if not data:
                return None
            value = data.get('value')
            expire = data.get('timeout')

            if expire and time.time() > expire:
                print "Checking for update of key.."
                if self.GetUpdate(key):
                    del self.cache[key]
                    return None
                else:
                    self.cache[key]['timeout'] = time.time() + timeout

            if len(self.cache) > 500:
                print("Initiating flush...")
                self.flushexpired()

            return value

    def GetUpdate(self, key):
        try:
            data = self.cache[key]
            host = data.get('host')
            etag = data.get('Etag')
            path = data.get('path')

            if not host:
                raise ValueError
            if not etag:
                raise ValueError
            if not path:
                raise ValueError

            p = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            p.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            p.connect((host, 80))

            http_request_header = "%s %s %s\nIf-None-Match: %s\nHost: %s\nConnection: close\r\n\r\n" % (
                "GET", path, "HTTP/1.1", '"' + str(etag) + '"', host)
            p.send(http_request_header)
            chunks = []
            bytes_recd = 0
            while True:
                chunk = p.recv(2048)
                if not chunk:
                    break
                chunks.append(chunk)
                bytes_recd = bytes_recd + len(chunk)

            response = b''.join(chunks)
            p.close()

            if "304 Not Modified" in response.split('\r\n\r\n')[0].splitlines()[0]:
                return False
            else:
                return True

        except ValueError:
            return False

        except socket.error:
            return False

    def get_count(self):
        return len(self.cache)

    def clear(self):
        self.cache.clear()

    def flushexpired(self):
        lock = threading.RLock()
        with lock:
            for key, data in self.cache.items():
                value = data.get('value')
                expire = data.get('timeout')
                if expire and time.time() > expire:
                    del self.cache[key]


# Function to return MD5 has of given URL
# MD5 hash is used as key to cache
def hasher(url):
    return hashlib.md5(url).hexdigest()

# Function to start proxy server and create threads for incoming requests from browsers
# Also initializes Cache with timeout if specified by user or 120 seconds
def StartProxy(port,timeout=False):
    try:
        host = ('127.0.0.1', port)
        proxy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        proxy.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        proxy.bind(host)
        proxy.listen(50)
        print 'Serving PoxyServer on port %s ...' % str(host)

        # if user has specified timeout then use it
        if timeout:
            Cache = ProxyCache(timeout=timeout)
        else:
            Cache = ProxyCache()
        while True:
            # Accept new request from clients
            client_connection, client_address = proxy.accept()
            # Create a new thread for every request
            # handler - is the function which servers http response
            # id - program generated thread id
            # mode = 500 when there is configuration file error


            t = threading.Thread(target=handler, args=(client_connection, Cache))
            # start function will start the execution of the handler function
            t.start()

    except KeyboardInterrupt:
        Cache.clear()
        print("Exiting...")
        sys.exit(0)

# Handler function to handle incoming requests from browser
#   Checks for HTTP METHOD, as we su
def handler(client_connection, Cache):
    try:
        while True:
            request = client_connection.recv(10000)
            if not request:
                break

            client_req = request.splitlines()
            # Check the request format
            # Check if method is GET,PUT,etc
            # Check if http version is specified
            res, error = CheckRequestFormat(client_req)
            if not res:
                http_response = GenerateHttp400Response(version="HTTP/1.1", error=error)
                client_connection.sendall(http_response)
                break
            # Extra method, path and version from the header
            method, path, version, host = ExtractClientHeader(
                client_req)
            # print client_req[:210]
            # print method,path,version,host
            # Check if the method is supported by this web server
            # If not return 501 not implemented error
            check_501 = CheckRequestType(method)
            if not check_501:
                http_response = GenerateHttp501Response(version=version)
                client_connection.sendall(http_response)
                print("Breaking..")
                break

            has_keepalive = CheckForKeepAlive(client_req)
            if has_keepalive:
                # print has_keepalive
                # client_connection.setblocking(True)

                # Get timeout value from configuration file
                client_connection.settimeout(10.0)
                if method == "GET":
                    http_response = GenerateHttpResponse(request, path, Cache,has_keepalive=has_keepalive, version=version, method=method,
                                                         host=host)
                client_connection.sendall(http_response)
            else:
                if method == "GET":
                    http_response = GenerateHttpResponse(request,path, Cache,has_keepalive=False, version=version, method=method, host=host)
                client_connection.sendall(http_response)
                break
    except socket.timeout:
        # timeout occurred after the last keep alive message
        # Time to close the socket and kill the thread
        client_connection.close()
    except socket.error:
        pass
    except ValueError:
        print "exception caught"

    # if connection was not closed anywhere above then it will be closed here
    client_connection.close()

    # return to kill the thread
    # there are other ways to do this
    return False  # Function to extract method,path,http version


# Function to prefetch href links from url
# it will get all href links from a page and prefetch them
#   URL and data is stored in Cache
def StartPrefetching(request, host, port, Cache):
    try:
        soup = BeautifulSoup(request, "lxml")
        i = 1

        # Extract all a links from
        for link in soup.find_all('a',href=True):
            i += 1
            dpath = link.get('href')
            if dpath:
                if 'https' in dpath:
                    continue
                p = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                p.settimeout(5.0)
                p.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

                if dpath.startswith("http"):
                    path = dpath
                    match = re.match(r'^.*?://([a-zA-Z0-9_.:]+)/', path)
                    if match:
                        host = match.group(1)
                    else:
                        match2 = re.match(r'^.*?://([a-zA-Z0-9_.:]+)', path)
                        host = match2.group(1)

                    if not path.endswith('/'):
                        path += '/'
                else:
                    if not dpath.startswith('/'):
                        path = "http://" + host + '/' + dpath
                    else:
                        path = "http://" + host + dpath
                    if not path.endswith('.html') and not path.endswith('/'):
                        path += "/"

                try:
                    if ":" in host:
                        p.connect((host.split(':')[0], int(host.split(':')[1])))
                    else:
                        p.connect((host, 80))
                except socket.gaierror:
                    continue

                http_request_header = "%s %s %s\nHost: %s\nConnection: Close\r\n\r\n" % ("GET", path, "HTTP/1.1", host)
                p.send(http_request_header)
                chunks = []
                while True:
                    chunk = p.recv(2048)
                    if not chunk:
                        break
                    chunks.append(chunk)
                response = b''.join(chunks)
                p.close()

                response_header = response.split('\r\n\r\n')[0]

                etag = GetEtag(response_header)
                # tocache = CheckCacheControl(response_header)

                incache = Cache.get(hasher(path))
                if not incache:
                    timeout = GetTimeoutValue(response_header)
                    if timeout:
                        Cache.set(hasher(path), response, etag, host, path, timeout)
                    else:
                        Cache.set(hasher(path), response, etag, host, path)

            if i > 50:
                print "Prefetching done..."
                return
    except KeyboardInterrupt:
        print("Exiting...")
        sys.exit(0)
    except socket.error:
        pass

    print "Prefetching done..."
    return


# Function to parse the request and find keepalive flag
def CheckForKeepAlive(request):
    try:
        if request:

            # Need to parse the whole request as the keep alive flag is not always on 6th position
            # Different browsers send it in different format
            for r in request:
                if 'Connection:' in r:
                    conn_option = r.split(':')[1]

                    # this is again messed up !
                    # IE uses the flag as Keep-Alive and chrome as keep-alive
                    # My logic is to convert it to lower and then compare
                    if conn_option.strip().lower() == 'keep-alive' or conn_option.strip().lower() == 'keepalive':
                        return conn_option.strip()
    except ValueError:
        pass

    return None


# Generic function to create a http response
# Function can be used for http/1.0 and http/1.0
# It will properly set the keep alive flag or connection close flag as required
def GenerateHttpResponse(response1, path, Cache,has_keepalive, version, method, host):
    # Check if no path has been specified
    # Server will search for the default files
    response = ""
    tocache = False
    timeout = False
    etag = ""
    port = 80
    try:
        if method == "GET":
            if path:
                response = Cache.get(hasher(path))
                if response:
                    print "Fetched from cache : %s" % path
                if not response:
                    p = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    p.settimeout(5.0)
                    p.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    try:
                        if ":" in host:
                            port = int(host.split(':')[1])
                            hostname = host.split(':')[0]
                            p.connect((hostname, port))
                        else:
                            p.connect((host, 80))
                    except socket.gaierror:
                        pass

                    http_response = re.sub(r'(Accept-Encoding: .*)', 'Accept-Encoding: identity', response1)
                    p.send(http_response.replace('keep-alive', 'close'))
                    chunks = []
                    while True:
                        chunk = p.recv(2048)
                        if not chunk:
                            break
                        chunks.append(chunk)
                    response = b''.join(chunks)
                    if has_keepalive:
                        response = response.replace('close',has_keepalive).replace('Close',has_keepalive)

                    response_header = response.split('\r\n\r\n')[0]
                    for line in response_header.splitlines():
                        if "Content-Type: text/html" in line:
                            t = threading.Thread(target=StartPrefetching, args=(response, host, port, Cache))
                            # start function will start the execution of the handler function
                            t.start()

                    etag = GetEtag(response_header)
                    tocache = CheckCacheControl(response_header)

                    if tocache:
                        timeout = GetTimeoutValue(response_header)
                        if timeout:
                            Cache.set(hasher(path), response, etag, host, path, timeout)
                        else:
                            Cache.set(hasher(path), response, etag, host, path)

                    p.close()

    except socket.gaierror:
        response = ""

    except socket.timeout:
        response=""
        p.close()

    return response


# Function to check if page should be cached or not
# cache-control: no-cache = do not cache
def CheckCacheControl(response):
    for line in response.splitlines():
        if line.split(':')[0].lower() == "cache-control":
            if "no-cache" in line:
                return False
    return True

# Function to get time value if server allows to cache
# max-age= is the timeout value
def GetTimeoutValue(response):
    try:
        for line in response.splitlines():
            if line.split(':')[0].lower() == "cache-control":
                option = line.split(':')[1]
                if "max-age=" in line:
                    timeout = option.split("max-age=")[1].strip()
                    return float(timeout)
    except:
        return False

    return False

# Function to get Etag from header
# Etag can be sent to server to check if the content has been modified or not
def GetEtag(response):
    try:

        for line in response.splitlines():

            if line.split(':')[0].strip().lower() == "etag":
                return line.split()[1].strip().replace('"', '')
    except:
        pass
    return False


# Function to check request method
# Allowed request are set with the RequestMethodSupport directive in configuration file
def CheckRequestType(method):
    try:
        supportedmethods = "GET"
        if len(supportedmethods) > 1:
            if method != "GET":
                return False
        else:
            if method != supportedmethods:
                return False
    except ValueError:
        pass

    return True


# Function to return html page for 501 error
def GenerateHttp501Response(version):
    http_response_header = "%s 501 Not Implemented\nConnection: close\n\r\n" % (version)
    data = Get501FoundPage()
    return (http_response_header + data)


# Function to return html page for 501 error
def Get501FoundPage():
    return "<html><body>501 Not Implemented <<error type>>: <<requested data>></body></html>"


# Function to return html page for 500 error
def GenerateHttp500Response(version):
    http_response_header = "%s 500 Internal Server Error\nConnection: close\n\r\n" % (version)
    data = Get500FoundPage()
    return (http_response_header + data)


# Function to return html page for 500 error
def Get500FoundPage():
    return "<html><body> <h1> Internal Server Error</h1> </body> </html>"


def ExtractClientHeader(request):
    method = getpage = version = host = ""

    # http://www.google.com/
    extractpage = re.compile(r"^.*?://[a-zA-Z0-9_.]+(.*)")
    try:
        if request:
            # assuming required fields will be always 0th element
            # generally this is true, but could fail if not followed
            # Couldnt find any standard format.
            (method, path, version) = request[0].split()

            if path:
                check = extractpage.match(path)
                if check:
                    getpage = check.group(1)
            for line in request:
                if 'Host' in line:
                    host = line.split(':', 1)[1].strip()
                    break
            return (method, path, version, host)
    except ValueError:
        raise ValueError


# Check request header format
# Check list -
# 1. Method
# 2. URI format
# 3. HTTP version
def CheckRequestFormat(client_req):
    try:

        if len(client_req[0].split()) == 3:
            method = client_req[0].split()[0]
            #method, url, ver = client_req[0].split()
            methods = "GET"

            # Check if method is a valid http method
            if method not in methods:
                return False, "method"

            url = client_req[0].split()[1]
            # Check if the URI startes with /
            # There could be some more checks for example:
            # IE does not allow ":" in URI
            if 'HTTP/' in url:
                return False, "urlerror"

            ver = client_req[0].split()[2]
            # This server supports only HTTP/1.1 and HTTP/1.0
            # Anything other than those will be considered as in valid request
            if repr(ver).strip() == repr('HTTP/1.1') or repr(ver).strip() == repr('HTTP/1.0'):
                pass
            else:
                return False, "httpvererror"
        else:
            return False,"other"

    except ValueError:
        pass

    # if not error is found return true and no error
    return True, "no error"


# Function to return html page for 400 error
# Function will return appropriate html for type of error
def GenerateHttp400Response(version, error):
    http_response_header = "%s 400\nConnection: close\n\r\n" % (version)
    data = ""
    if error == "method":
        data = """
<html><body>400 Bad Request Reason: Invalid Method :<<request method>></body></html>
"""
    elif error == "urlerror":
        data = """
<html><body>400 Bad Request Reason: Invalid URL: <<requested url>></body></html>
"""
    elif error == "httpvererror":
        data = """
<html><body>400 Bad Request Reason: Invalid HTTP-Version: <<req version>></body></html>
"""
    else:
        data = """
        <html><body>400 Bad Request</body></html>
        """
    return (http_response_header + data)


if __name__ == "__main__":
    if len(sys.argv) == 3:
        if sys.argv[1].isdigit() and sys.argv[2].isdigit():
            StartProxy(int(sys.argv[1]),timeout=sys.argv[2])

    elif len(sys.argv) == 2:
        if sys.argv[1].isdigit():
            StartProxy(int(sys.argv[1]))
    else:
        print "Error: Incorrect arguments\nError: Example python2.7 webproxy.py 10001 120"
