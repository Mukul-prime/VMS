-- Run Step by Step to create database 

drop DATABASE vmsd;

CREATE DATABASE VMSD;

USE VMSD;


SELECT * FROM vmsd.cameras;

INSERT INTO Cameras 
(Cam_name, Cam_location, ip_address, rstp_url, username, password,created)
VALUES
('Camera 1', 'Noida', '192.168.1.116','rtsp://admin:Pratikshat%40123%23@192.168.1.111:554/stream1' , 'NOIDA', '40122', NOW()),

('Camera 2', 'Noida ','192.168.1.112', 'rtsp://admin:Pratikshat%40123%23@192.168.1.112:554/stream1', 'NOIDA', '40122', NOW()),

('Camera 3', 'Noida' ,'192.168.1.113', 'rtsp://admin:Pratikshat%40123%23@192.168.1.113:554/stream1', 'NOIDA', '40122', NOW()),

('Camera 4', 'Noida', '192.168.1.114', 'rtsp://admin:noida%40122@192.168.1.114:554/stream1', 'NOIDA', '40122', NOW()),

('Camera 5', 'Noida', '192.168.1.111','rtsp://admin:NOIDA%40122@192.168.1.115:554/stream1' , 'NOIDA', '40122', NOW()),

('Camera 6', 'Noida', '192.168.1.115', 'rtsp://admin:noida%40122@192.168.1.116:554/stream1', 'NOIDA', '40122', NOW());


drop DATABASE vmsd;