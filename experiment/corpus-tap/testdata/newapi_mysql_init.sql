-- Minimal New API-compatible schema for Corpus Tap integration tests.

CREATE DATABASE IF NOT EXISTS newapi CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE newapi;

CREATE TABLE IF NOT EXISTS tokens (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  `key` VARCHAR(191) NOT NULL,
  status INT NOT NULL DEFAULT 1,
  expired_time BIGINT NOT NULL DEFAULT -1,
  remain_quota BIGINT NOT NULL DEFAULT 0,
  unlimited_quota TINYINT(1) NOT NULL DEFAULT 0,
  created_time BIGINT NOT NULL DEFAULT 0,
  accessed_time BIGINT NOT NULL DEFAULT 0,
  UNIQUE KEY idx_tokens_key (`key`)
);

INSERT INTO tokens (id, user_id, `key`, status, expired_time) VALUES
  (1, 100, 'sk-integration-active', 1, -1),
  (2, 101, 'sk-integration-disabled', 2, -1),
  (3, 102, 'sk-integration-expired', 1, 1);

CREATE TABLE IF NOT EXISTS logs (
  id INT PRIMARY KEY AUTO_INCREMENT,
  request_id VARCHAR(64) NOT NULL,
  channel_id INT NOT NULL DEFAULT 0,
  prompt_tokens INT NOT NULL DEFAULT 0,
  completion_tokens INT NOT NULL DEFAULT 0,
  quota DOUBLE NOT NULL DEFAULT 0,
  created_at BIGINT NOT NULL DEFAULT 0,
  INDEX idx_logs_request_id (request_id)
);

INSERT INTO logs (request_id, channel_id, prompt_tokens, completion_tokens, quota)
VALUES ('mock-req-1', 3, 10, 5, 0.001);
