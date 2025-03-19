// create a python subprocess and communicate with it through network
import { request, RequestOptions } from 'http';

export class TesterSession {
    private updateMessageCallback?: (...args: any[]) => any;
    private errorCallbcak?: (...args: any[]) => any;
    private showNoRefMsg?: (...args: any[]) => any;
    private connectToPort: number;
    
    // setting connectToPort to 0 to start up an internal server
    constructor(updateMessageCallback?: (...args: any[]) => any, errorCallback?: (...args: any[]) => any, showNoRefMsg?: (...args: any[]) => any, connectToPort: number = 0) {
        this.updateMessageCallback = updateMessageCallback;
        this.errorCallbcak = errorCallback;
        this.showNoRefMsg = showNoRefMsg;
        this.connectToPort = connectToPort;
    }

    async changeJunitVersion(version: string) {
        const requestData = JSON.stringify({ type: 'change_junit_version', data: version });

        const options: RequestOptions = {
            hostname: 'localhost',
            port: this.connectToPort,
            path: '/junitVersion',
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Content-Length': requestData.length.toString()
            }
        };

        let finish: (value?: any) => void;
        const finishePromise = new Promise((res, rej) => { finish = res; });
        
        const req = request(options, (res) => {
            if (res.statusCode !== 200) {
                throw new Error('Failed request from server.');
            }

            res.on('error', (e) => {
                console.error(e);
            });
        });

        req.on('error', (e) => {
            console.error(`Problem on request: ${e}`);
        });

        req.write(requestData + '\n');
        req.end();
        await finishePromise;
    }

    async startQuery(args: any, cancelCb: (e: any) => any) {
        const requestData = JSON.stringify({ type: 'query', data: args });

        const options: RequestOptions = {
            hostname: 'localhost',
            port: this.connectToPort,
            path: '/session',
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Content-Length': requestData.length.toString()
            }
        };

        let finish: (value?: any) => void;
        const finishePromise = new Promise((res, rej) => { finish = res; });
        const req = request(options, (res) => {
            let status = 'before-start';

            if (res.statusCode !== 200) {
                throw new Error('Failed request from server.');
            }

            res.on('data', (chunk) => {
                try {
                    const msg = JSON.parse(chunk.toString());
                    if (status === 'before-start') {
                        // confirm start
                        if (!(msg.type && msg.data && msg.type === 'status' && msg.data.status === 'start')) {
                            throw TypeError('Failed to receive start message');
                        }
                        status = 'started';
                    } else if (status !== 'finished') {
                        // receive messages
                        if (msg.type && msg.data) {
                            if (msg.type === 'status' && msg.data.status === 'finish') {
                                status = 'finished';
                                finish();
                                return;
                            } else if (msg.type === 'msg' && msg.data.session_id && msg.data.messages) {
                                if (this.updateMessageCallback) {
                                    this.updateMessageCallback(msg.data.messages);
                                }
                            } else if (msg.type === 'noreference' && msg.data.session_id) {
                                const junit_version = msg.data.junit_version;
                                if (this.showNoRefMsg) {
                                    this.showNoRefMsg(junit_version);
                                }
                            } else {
                                throw TypeError('Invalid message type');
                            }
                        } else {
                            throw TypeError('Invalid message format');
                        }
                        console.log(msg);
                    }
                    
                } catch (e) {
                    console.error(e);
                    cancelCb(e);
                }
            });

            res.on('end', () => {
                console.log('No more data in response.');
                // this.close();
            });

            res.on('error', (e) => {
                console.error(e);
            });
        });

        req.on('error', (e) => {
            console.error(`Problem on request: ${e}`);
        });
        req.write(requestData + '\n');
        req.end();
        await finishePromise;
    }
}
