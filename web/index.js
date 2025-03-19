const noMessagePrompt = document.getElementById('no-message');
const chatContainer = document.getElementById('chat-container');
const userInput = document.getElementById('user-input');
const body = document.getElementsByTagName('body')[0];

body.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') {
        sendMessage();
    }
});

function timeout(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function onClickForMessage(msg) {
    return () => {
        if (msg.classList.contains('expand')) {
            msg.classList.remove('expand');
            msg.style.maxHeight = "5px";
        } else {
            msg.classList.add('expand');
            msg.style.maxHeight = msg.scrollHeight + 'px';
        }
    }
}

function createMessageContent(message, isHtml) {
    const messageContentElement = document.createElement('div');
    messageContentElement.className = 'message-content'
    if (isHtml) {
        messageContentElement.innerHTML = message;
    }
    else {
        messageContentElement.textContent = message;
    }

    let toInput = false;
    let originalHtml = '';

    let switchToOk = () => {
        if (toInput) {
            const newRaw = messageContentElement.querySelector('textarea').value;
            const newRawHtml = marked.parse(newRaw);
            messageContentElement.innerHTML = newRawHtml;
            messageContentElement.querySelectorAll('pre code').forEach((block) => {
                hljs.highlightElement(block);
            });
            messageContentElement.querySelectorAll('code').forEach((block) => {
                const buttonSvg = '<svg xmlns="http://www.w3.org/2000/svg" height="16px" viewBox="0 -960 960 960" width="16px" fill="#5f6368"><path d="M189.06-113.3q-31 0-53.38-22.38-22.38-22.38-22.38-53.38v-581.88q0-31.06 22.38-53.49 22.38-22.43 53.38-22.43H466v75.92H189.06v581.88h581.88V-466h75.92v276.94q0 31-22.43 53.38Q802-113.3 770.94-113.3H189.06Zm201.08-223.37-52.81-53.47 380.81-380.8H532.67v-75.92h314.19v314.19h-75.92v-184.8l-380.8 380.8Z"></path></svg>'
                const button = document.createElement('button');
                button.className = 'open-code-button';
                button.attributes.title = 'Open';
                button.onclick = (e) => {
                    let lang;
                    for (const cls of block.classList) {
                        if (cls.startsWith('language-')) {
                            lang = cls.substring('language-'.length);
                            break;
                        }
                    }
                    e.stopPropagation();
                    window.vscode?.postMessage({ cmd: 'open-code', content: block.textContent, lang: lang });
                };
                button.innerHTML = buttonSvg;
                block.appendChild(button);

                block.addEventListener('mousemove',() => { button.classList.add('show'); });
                block.addEventListener('mouseleave',() => {
                    button.classList.remove('show');
                });
                {
                    const buttonSvg = '<svg xmlns="http://www.w3.org/2000/svg" height="16px" viewBox="0 -960 960 960" width="16px" fill="#5f6368"><path d="M480-100q-70.77 0-132.61-26.77-61.85-26.77-107.85-72.77-46-46-72.77-107.85Q140-369.23 140-440h60q0 117 81.5 198.5T480-160q117 0 198.5-81.5T760-440q0-117-81.5-198.5T480-720h-10.62l63.54 63.54-42.15 43.38-136.92-137.3 137.69-137.31 42.15 43.38L469.38-780H480q70.77 0 132.61 26.77 61.85 26.77 107.85 72.77 46 46 72.77 107.85Q820-510.77 820-440q0 70.77-26.77 132.61-26.77 61.85-72.77 107.85-46 46-107.85 72.77Q550.77-100 480-100Z"/></svg>';
                    const restartButton = document.createElement('button');
                    restartButton.className = 'restart-from-here-button';
                    restartButton.attributes.title = 'Restart with this';
                    restartButton.onclick = (e) => {
                        e.stopPropagation();
                        window.vscode?.postMessage({ cmd: 'restart-session', number: messageContentElement.parentElement.index });
                    };
                    restartButton.innerHTML = buttonSvg;
                    block.appendChild(restartButton);

                    block.onmousemove = () => { restartButton.classList.add('show'); };
                    block.onmouseleave = () => {
                        restartButton.classList.remove('show');
                    };
                }
            });
            toInput = false;
        }
    };
    let switchToModify = () => {
        if (!toInput) {
            // originalHtml = messageContentElement.innerHTML;
            const modifyInput = document.createElement('textarea');
            modifyInput.cols = 100;
            modifyInput.rows = 8;
            modifyInput.style.display = 'block';
            modifyInput.style.width = '100%';
            modifyInput.style.margin = '0.5em 0';
            modifyInput.style.padding = '0.3em';
            modifyInput.style.resize = 'none';
            modifyInput.style.overflow = 'auto';
            modifyInput.style.boxSizing = 'border-box';
            modifyInput.value = raw;
            const okButton = document.createElement('button');
            okButton.textContent = 'Submit';
            okButton.style.margin = '0 0 0.5em 0';
            okButton.onclick = (e) => {
                switchToOk();
                e?.stopPropagation();
            };
            messageContentElement.innerHTML = '';
            messageContentElement.appendChild(modifyInput);
            messageContentElement.appendChild(okButton);
            toInput = !toInput;
        }
    };
    messageContentElement.switchToOk = switchToOk;
    
    
    messageContentElement.addEventListener('click', () => {
        if (!toInput) {
            // const scrollTop = messageContentElement.scrollTop;
            liveContentContainers?.switchToOk();
            liveContentContainers = messageContentElement;

            switchToModify();
            
            messageContentElement.scrollIntoView({ block: 'center' });
            // messageContentElement.scrollTop = scrollTop;

            toInput = true;
        }
    });
    return messageContentElement;
}

let total_messages = 0;

function addMessage(message, raw, sender, isHtml, senderType) {
    const messageContentElement = createMessageContent(message, raw, isHtml);

    const messageElement = document.createElement('div');
    messageElement.appendChild(messageContentElement);
    messageElement.className = 'message before-show ' + sender;

    const messageHeader = document.createElement('div');
    messageHeader.className = 'message-header';
    if (!senderType) {
        senderType = sender;
    }
    messageHeader.textContent = senderType[0].toUpperCase() + senderType.substring(1);

    chatContainer.appendChild(messageHeader);
    chatContainer.appendChild(messageElement);

    // doScroll();
    messageElement.index = total_messages;
    return messageElement;
}

window.lastMouseTime = Date.now(); 
body.addEventListener('mousewheel', function (e) {
    window.lastMouseTime = Date.now(); 
});
body.addEventListener('mousedown', function (e) {
    window.lastMouseTime = Date.now(); 
});
function doScroll() {
    if (!(window.lastMouseTime && Date.now() - window.lastMouseTime < 3000)) {
        body.scrollTo({
            top: body.scrollHeight,
            behavior: 'smooth'
        });
    }
}

function showTypingAnimation(sender) {
    addMessage('<div style="padding: 10px;"><span></span><span></span><span></span></div>', 'typing ' + sender, true, sender);
}

function completeTypingAnimation(html, sender) {
    const typingElement = document.querySelector('.typing');
    if (typingElement) {
        typingElement.className = 'message ' + sender;
        typingElement.innerHTML = '';
        typingElement.appendChild(createMessageContent(html, raw, true));
        // doScroll();
        typingElement.index = total_messages;
        return typingElement;
    }
    return undefined;
}

function removeTypingAnimation() {
    const typingElement = document.querySelector('.typing');
    if (typingElement) {
        chatContainer.removeChild(typingElement);
    }
}

const canConnectToVsCode = (window.acquireVsCodeApi !== undefined);
if (canConnectToVsCode) {
    window.vscode = acquireVsCodeApi();
}

window.addEventListener('message', async (event) => {
    console.log(event.data);
    msg = event.data;
    if (msg.role && msg.content) {
        noMessagePrompt.style.display = 'none';

        if (msg.role.endsWith('-wait')) {
            msg.role = msg.role.substring(0, msg.role.length - '-wait'.length);
            showTypingAnimation(msg.role);
        } else {
            let messageElement = completeTypingAnimation(msg.content, msg.raw, msg.role)
                ?? addMessage(msg.content, msg.raw, msg.role, true);
            total_messages = total_messages + 1;
            messageElement.querySelectorAll('pre code').forEach((block) => {
                hljs.highlightElement(block);
            });
            messageElement.querySelectorAll('code').forEach((block) => {
                const buttonSvg = '<svg xmlns="http://www.w3.org/2000/svg" height="16px" viewBox="0 -960 960 960" width="16px" fill="#5f6368"><path d="M189.06-113.3q-31 0-53.38-22.38-22.38-22.38-22.38-53.38v-581.88q0-31.06 22.38-53.49 22.38-22.43 53.38-22.43H466v75.92H189.06v581.88h581.88V-466h75.92v276.94q0 31-22.43 53.38Q802-113.3 770.94-113.3H189.06Zm201.08-223.37-52.81-53.47 380.81-380.8H532.67v-75.92h314.19v314.19h-75.92v-184.8l-380.8 380.8Z"></path></svg>'
                const button = document.createElement('button');
                button.className = 'open-code-button';
                button.attributes.title = 'Open';
                button.onclick = (e) => {
                    let lang;
                    for (const cls of block.classList) {
                        if (cls.startsWith('language-')) {
                            lang = cls.substring('language-'.length);
                            break;
                        }
                    }
                    e.stopPropagation();
                    window.vscode?.postMessage({ cmd: 'open-code', content: block.textContent, lang: lang });
                }
                button.innerHTML = buttonSvg;
                block.appendChild(button);

                block.addEventListener('mousemove',() => { button.classList.add('show'); });
                block.addEventListener('mouseleave',() => {
                    button.classList.remove('show');
                });
                {
                    const buttonSvg = '<svg xmlns="http://www.w3.org/2000/svg" height="16px" viewBox="0 -960 960 960" width="16px" fill="#5f6368"><path d="M480-100q-70.77 0-132.61-26.77-61.85-26.77-107.85-72.77-46-46-72.77-107.85Q140-369.23 140-440h60q0 117 81.5 198.5T480-160q117 0 198.5-81.5T760-440q0-117-81.5-198.5T480-720h-10.62l63.54 63.54-42.15 43.38-136.92-137.3 137.69-137.31 42.15 43.38L469.38-780H480q70.77 0 132.61 26.77 61.85 26.77 107.85 72.77 46 46 72.77 107.85Q820-510.77 820-440q0 70.77-26.77 132.61-26.77 61.85-72.77 107.85-46 46-107.85 72.77Q550.77-100 480-100Z"/></svg>';
                    const restartButton = document.createElement('button');
                    restartButton.className = 'restart-from-here-button';
                    restartButton.attributes.title = 'Restart with this';
                    restartButton.onclick = (e) => {
                        e.stopPropagation();
                        window.vscode?.postMessage({ cmd: 'restart-session', number: messageElement.index });
                    };
                    restartButton.innerHTML = buttonSvg;
                    block.appendChild(restartButton);

                    block.onmousemove = () => { restartButton.classList.add('show'); };
                    block.onmouseleave = () => {
                        restartButton.classList.remove('show');
                    };
                }
            });
        }
    } else if (msg.cmd) {
        if (msg.cmd === 'error') {
            // TODO add error processing
        } else if (msg.cmd === 'clear') {
            // TODO clear the chat and show no-message prompt again
            const n = msg.toIndex ?? 0;
            total_messages = n;
            while (chatContainer.children.length > 2 * n) {
                chatContainer.removeChild(chatContainer.lastChild);
            }
        }
    }
});