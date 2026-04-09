const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const { createClient } = require('redis');
const cors = require('cors');

const app = express();
app.use(cors());
const server = http.createServer(app);

// Allow React to connect
const io = new Server(server, {
    cors: { origin: "http://localhost:5173", methods: ["GET", "POST"] } 
});

// We need TWO clients. One to listen, one to talk.
const redisSubscriber = createClient({ url: 'redis://localhost:6379' });
const redisPublisher = createClient({ url: 'redis://localhost:6379' });

redisSubscriber.on('error', (err) => console.error('Redis Sub Error', err));
redisPublisher.on('error', (err) => console.error('Redis Pub Error', err));

async function startBridge() {
    await redisSubscriber.connect();
    await redisPublisher.connect();
    console.log("✅ Node Server connected to Redis! (Pub/Sub active)");

    io.on('connection', (socket) => {
        console.log('💻 Dashboard UI Connected!'); // THIS PROVES THE NEW CODE IS RUNNING
        
        socket.on('send_command', async (cmdData) => {
            console.log("⚡ Command received from UI:", cmdData.command);
            await redisPublisher.publish('manager_control', JSON.stringify(cmdData));
        });
        
        socket.on('disconnect', () => console.log('💻 Dashboard UI Disconnected.'));
    });

    await redisSubscriber.subscribe('f1_telemetry_stream', (message) => {
        const parsedData = JSON.parse(message);
        io.emit('f1_telemetry', parsedData);
    });

    server.listen(4000, () => {
        console.log("🚀 WebSocket Bridge running on http://localhost:4000");
    });
}

startBridge();