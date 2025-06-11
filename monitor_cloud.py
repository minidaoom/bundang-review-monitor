#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏥 분당제일여성병원 네이버 지도 리뷰 모니터링 시스템 (클라우드 버전)
GitHub Actions에서 실행되는 완전 자동화 시스템
"""

import os
import json
import requests
import smtplib
import re
import logging
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup

class BundangCloudMonitor:
    def __init__(self):
        self.url = "https://map.naver.com/p/search/분당제일여성병원/place/11830416"
        self.history_file = "review_history.json"
        self.log_file = "monitor.log"
        
        self.recipient_email = os.environ.get('RECIPIENT_EMAIL', '')
        self.gmail_address = os.environ.get('GMAIL_ADDRESS', '')
        self.gmail_password = os.environ.get('GMAIL_PASSWORD', '')
        self.test_mode = os.environ.get('TEST_MODE', 'false').lower() == 'true'
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
    def validate_settings(self):
        if not all([self.recipient_email, self.gmail_address, self.gmail_password]):
            self.logger.error("❌ 이메일 설정이 누락되었습니다!")
            return False
        return True
    
    def get_review_count(self):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(self.url, headers=headers, timeout=15)
            response.raise_for_status()
            
            patterns = [
                r'리뷰\s*(\d+)',
                r'review\s*(\d+)',
                r'후기\s*(\d+)'
            ]
            
            all_numbers = []
            for pattern in patterns:
                matches = re.findall(pattern, response.text, re.IGNORECASE)
                if matches:
                    all_numbers.extend([int(m) for m in matches])
            
            if all_numbers:
                valid_numbers = [n for n in all_numbers if 100 <= n <= 10000]
                if valid_numbers:
                    return max(valid_numbers)
            return None
        except Exception as e:
            self.logger.error(f"❌ 리뷰 개수 조회 실패: {e}")
            return None
    
    def send_email_notification(self, old_count, new_count, change_type="change"):
        try:
            change = new_count - old_count if old_count else 0
            
            if change > 0:
                change_text = f"+{change}"
                emoji = "📈"
                change_desc = "증가"
            elif change < 0:
                change_text = str(change)
                emoji = "📉"
                change_desc = "감소"
            else:
                change_text = "±0"
                emoji = "📊"
                change_desc = "변화없음"
            
            if change_type == "start":
                subject = "🎯 분당제일여성병원 리뷰 모니터링 시작!"
            else:
                subject = f"🚨 {emoji} 분당제일여성병원 리뷰 {change_desc}!"
            
            current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            
            body = f"""
🏥 분당제일여성병원 네이버 지도 리뷰 알림

{emoji} 변화 내용:
   이전 리뷰 수: {old_count if old_count else '알 수 없음'}개
   현재 리뷰 수: {new_count}개
   변화량: {change_text}개

⏰ 감지 시간: {current_time}
🔗 네이버 지도: {self.url}

---
🤖 GitHub Actions 자동 모니터링 시스템
💻 컴퓨터를 꺼놔도 24시간 자동 실행됩니다!
            """
            
            msg = MIMEMultipart()
            msg['From'] = self.gmail_address
            msg['To'] = self.recipient_email
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(self.gmail_address, self.gmail_password)
            server.sendmail(self.gmail_address, self.recipient_email, msg.as_string())
            server.quit()
            
            self.logger.info(f"✅ 이메일 전송 완료: {old_count or 0} → {new_count} ({change_text})")
            return True
        except Exception as e:
            self.logger.error(f"❌ 이메일 전송 실패: {e}")
            return False
    
    def run_monitoring(self):
        try:
            if not self.validate_settings():
                return False
            
            current_count = self.get_review_count()
            if current_count is None:
                self.logger.error("❌ 리뷰 개수를 가져올 수 없습니다.")
                return False
            
            history = []
            if os.path.exists(self.history_file):
                try:
                    with open(self.history_file, 'r', encoding='utf-8') as f:
                        history = json.load(f)
                except:
                    pass
            
            last_count = None
            if history:
                last_count = history[-1].get('review_count')
            
            new_record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "review_count": current_count,
                "previous_count": last_count,
                "change": current_count - last_count if last_count else 0
            }
            
            should_notify = False
            change_type = "change"
            
            if last_count is None:
                should_notify = True
                change_type = "start"
            elif current_count != last_count:
                should_notify = True
            
            if self.test_mode:
                should_notify = True
                change_type = "test"
            
            if should_notify:
                success = self.send_email_notification(last_count, current_count, change_type)
                new_record["notification_sent"] = success
            else:
                new_record["notification_sent"] = False
            
            history.append(new_record)
            history = history[-50:]  # 최근 50개만 보관
            
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
            
            self.logger.info("🎉 모니터링 완료!")
            return True
        except Exception as e:
            self.logger.error(f"❌ 모니터링 실행 중 오류: {e}")
            return False

def main():
    print("🎉 GitHub Actions 분당제일여성병원 리뷰 모니터링 시작!")
    monitor = BundangCloudMonitor()
    success = monitor.run_monitoring()
    
    if success:
        print("✅ 모니터링 성공적으로 완료!")
    else:
        print("❌ 모니터링 실행 중 오류 발생")
        exit(1)

if __name__ == "__main__":
    main()
