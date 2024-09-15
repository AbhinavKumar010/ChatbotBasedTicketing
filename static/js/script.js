const userId = 'user1'; // Example user ID
const stripe = Stripe('your_publishable_key');
const elements = stripe.elements();
const card = elements.create('card');
card.mount('#card-element');

document.getElementById('send-btn').addEventListener('click', function() {
    const userInput = document.getElementById('user-input').value.trim();
    if (userInput) {
        fetch('/webhook', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: userId,
                queryInput: { text: { text: userInput } }
            })
        })
        .then(response => response.json())
        .then(data => {
            addMessage('Bot: ' + data.fulfillmentText, 'bot');
            document.getElementById('user-input').value = '';
        })
        .catch(error => {
            console.error('Error:', error);
            addMessage('Sorry, there was an error processing your request. Please try again later.', 'bot');
        });
    }
});


let mediaRecorder;
let audioChunks = [];

// Start or stop recording when the button is clicked
document.getElementById('record-btn').addEventListener('click', async () => {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        alert('Your browser does not support audio recording.');
        return;
    }

    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);

        mediaRecorder.ondataavailable = event => {
            audioChunks.push(event.data);
        };

        mediaRecorder.onstop = () => {
            const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
            const audioUrl = URL.createObjectURL(audioBlob);
            const audioElement = document.getElementById('response-audio');
            audioElement.src = audioUrl;
            audioElement.play(); // Automatically play the audio

            // Send audioBlob to server
            sendAudioToServer(audioBlob);

            audioChunks = []; // Clear the chunks for the next recording
        };

        // Toggle recording state
        if (mediaRecorder.state === 'inactive') {
            mediaRecorder.start();
            document.getElementById('record-btn').textContent = 'Stop Recording';
        } else {
            mediaRecorder.stop();
            document.getElementById('record-btn').textContent = 'Start Recording';
        }
    } catch (err) {
        console.error('Error accessing audio devices:', err);
        alert('An error occurred while accessing the audio devices. Please try again.');
    }
});

// Function to send the recorded audio to the server
function sendAudioToServer(blob) {
    const formData = new FormData();
    formData.append('file', blob, 'recording.wav');

    fetch('/voice-chat', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        console.log('Server response:', data);
        // Optionally, you can display a message to the user
        appendMessage('Audio successfully sent to the server.', 'bot-message');
    })
    .catch(error => {
        console.error('Error uploading audio:', error);
        appendMessage('Error uploading audio. Please try again.', 'bot-message');
    });
}

// Function to append messages to the chat
function appendMessage(message, className) {
    const messageContainer = document.createElement('div');
    messageContainer.className = `message ${className}`;
    messageContainer.textContent = message;
    document.querySelector('.messages').appendChild(messageContainer);
    document.querySelector('.messages').scrollTop = document.querySelector('.messages').scrollHeight; // Scroll to the bottom
}

// Simulate a bot response for demonstration purposes
function simulateBotResponse(userMessage) {
    setTimeout(() => {
        appendMessage('This is a simulated response', 'bot-message');
    }, 1000);
}


document.getElementById('language-select').addEventListener('change', function() {
    const selectedLanguage = this.value;
    fetch('/select_language', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, language: selectedLanguage })
    })
    .then(response => response.json())
    .then(data => {
        addMessage(data.message, 'bot');
    });
});

document.getElementById('clear-chat-btn').addEventListener('click', function() {
    document.querySelector('.messages').innerHTML = '';
});

document.getElementById('book-btn').addEventListener('click', function() {
    const show = document.getElementById('show-select').value;
    alert(`Please Complete Payment First For ${show}!`);
});

document.getElementById('confirm-pay-btn').addEventListener('click', function() {
    fetch('/create-payment-intent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ amount: 5000 }) // Amount in cents
    })
    .then(response => response.json())
    .then(data => {
        return stripe.confirmCardPayment(data.clientSecret, {
            payment_method: {
                card: card,
                billing_details: {
                    name: 'Customer',
                },
            },
        });
    })
    .then(result => {
        if (result.error) {
            alert('Payment failed: ' + result.error.message);
        } else {
            if (result.paymentIntent.status === 'succeeded') {
                alert('Payment successful!');
            }
        }
    })
    .catch(error => {
        console.error('Error:', error);
    });
});

function addMessage(message, sender) {
    const messageDiv = document.createElement('div');
    messageDiv.classList.add('message');
    if (sender === 'bot') {
        messageDiv.classList.add('bot-message');
    }
    messageDiv.textContent = message;
    document.querySelector('.messages').appendChild(messageDiv);
    document.querySelector('.messages').scrollTop = document.querySelector('.messages').scrollHeight;
}
