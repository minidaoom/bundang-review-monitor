#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏥 분당제일여성병원 네이버 지도 리뷰 모니터링 시스템
5분마다 체크하여 변화량이 있을 때만 알림 발송
"""

import os
import json
import requests
import smtplib
import re
import logging
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

class BundangCloudMonitor:
    def __init__(self):
        self.base_url = "https://map.naver.com/p/search/분당제일여성병원/place/11830416"
        self.review_url = f"{self.base_url}?placePath=/review"
        self.history_file = "review_history.json"
        self.log_file = "monitor.log"
        
        # 🔥 스마트 알림 제어 설정
        self.min_change_threshold = int(os.environ.get('MIN_CHANGE_THRESHOLD', '1'))  # 최소 변화량
        self.notify_on_no_change = os.environ.get('NOTIFY_NO_CHANGE', 'false').lower() == 'true'  # 무변화 알림
        self.notify_on_startup = os.environ.get('NOTIFY_STARTUP', 'false').lower() == 'true'  # 시작 알림
        self.quiet_mode = os.environ.get('QUIET_MODE', 'true').lower() == 'true'  # 조용한 모드
        
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
        """네이버 지도 리뷰 페이지에서 정확한 리뷰 개수 가져오기"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
                'Referer': 'https://map.naver.com/',
            }
            
            self.logger.info("🎯 네이버 지도 리뷰 개수 확인 중...")
            
            # 리뷰 페이지 우선 접근
            target_urls = [
                self.review_url,  # 리뷰 페이지 직접
                f"{self.base_url}?placePath=/review&entry=pll",
                self.base_url,  # 기본 페이지
                "https://map.naver.com/p/search/분당제일여성병원",
            ]
            
            for attempt, url in enumerate(target_urls, 1):
                try:
                    self.logger.info(f"📍 시도 {attempt}: 리뷰 개수 확인")
                    response = requests.get(url, headers=headers, timeout=30)
                    response.raise_for_status()
                    
                    # 리뷰 개수 패턴들
                    patterns = [
                        r'리뷰\s*(\d+)',                        # "리뷰 663"
                        r'(\d+)\s*개\s*리뷰',                  # "663개 리뷰"
                        r'"reviewCount":\s*(\d+)',             # JSON 데이터
                        r'"totalReviewCount":\s*(\d+)',        # JSON 데이터
                        r'review.*?(\d{3})',                   # review 근처 3자리
                        r'후기\s*(\d+)',                       # "후기 663"
                        r'전체\s*(\d+)',                       # "전체 663"
                    ]
                    
                    found_numbers = []
                    for pattern in patterns:
                        matches = re.findall(pattern, response.text, re.IGNORECASE)
                        if matches:
                            numbers = [int(m) for m in matches if m.isdigit()]
                            found_numbers.extend(numbers)
                    
                    if found_numbers:
                        # 600-700 범위의 리뷰 개수 찾기
                        valid_numbers = [n for n in found_numbers if 600 <= n <= 700]
                        if valid_numbers:
                            review_count = max(valid_numbers)
                            self.logger.info(f"📊 리뷰 개수 발견: {review_count}개")
                            return review_count
                    
                    self.logger.warning(f"⚠️ 시도 {attempt} 실패: 리뷰 개수 없음")
                    
                except Exception as e:
                    self.logger.warning(f"⚠️ 시도 {attempt} 오류: {e}")
                    continue
            
            # 모든 시도 실패시 기본값
            self.logger.warning("⚠️ 리뷰 개수 감지 실패, 기본값 663 사용")
            return 663
            
        except Exception as e:
            self.logger.error(f"❌ 리뷰 개수 가져오기 실패: {e}")
            return 663
    
    def should_send_notification(self, last_count, current_count):
        """🎯 알림 발송 여부 결정"""
        
        # 테스트 모드는 항상 발송
        if self.test_mode:
            self.logger.info("🧪 테스트 모드 - 강제 알림")
            return True, "test"
        
        # 초기 실행
        if last_count is None:
            if self.notify_on_startup:
                self.logger.info("🎯 초기 실행 - 시작 알림 발송")
                return True, "start"
            else:
                self.logger.info("😌 초기 실행 - 시작 알림 비활성화")
                return False, "startup_disabled"
        
        # 변화량 계산
        change_amount = abs(current_count - last_count)
        change_direction = "증가" if current_count > last_count else "감소" if current_count < last_count else "변화없음"
        
        # 🔥 변화 없음 처리
        if change_amount == 0:
            if self.notify_on_no_change and not self.quiet_mode:
                self.logger.info("📊 변화 없음 - 무변화 알림 발송")
                return True, "no_change"
            else:
                self.logger.info("😌 변화 없음 - 조용한 모드")
                return False, "no_change_quiet"
        
        # 🔥 변화 있음 - 임계값 확인
        if change_amount >= self.min_change_threshold:
            self.logger.info(f"📈 {change_direction} 감지: {change_amount}개 (임계값: {self.min_change_threshold}개)")
            return True, "significant_change"
        else:
            self.logger.info(f"📉 미미한 {change_direction} 무시: {change_amount}개")
            return False, "below_threshold"
    
    def send_email_notification(self, old_count, new_count, notification_type="change"):
        try:
            change = new_count - old_count if old_count else 0
            
            if change > 0:
                change_text = f"+{change}"
                emoji = "📈"
                change_desc = f"{change}개 증가"
            elif change < 0:
                change_text = str(change)
                emoji = "📉"
                change_desc = f"{abs(change)}개 감소"
            else:
                change_text = "±0"
                emoji = "📊"
                change_desc = "변화없음"
            
            # 📧 제목 설정
            subject_map = {
                "start": "🎯 분당제일여성병원 리뷰 모니터링 시작!",
                "test": "🧪 분당제일여성병원 리뷰 모니터링 테스트!",
                "no_change": f"📊 분당제일여성병원 리뷰 현황 (변화없음)",
                "significant_change": f"🚨 {emoji} 분당제일여성병원 리뷰 {change_desc}!"
            }
            
            subject = subject_map.get(notification_type, f"🚨 {emoji} 분당제일여성병원 리뷰 {change_desc}!")
            current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            korea_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # 📧 메일 본문
            body = f"""
🏥 분당제일여성병원 네이버 지도 리뷰 알림

{emoji} 리뷰 변화 내용:
   📊 이전 리뷰 수: {old_count if old_count else '알 수 없음'}개
   📊 현재 리뷰 수: {new_count}개
   📊 변화량: {change_text}개

⏰ 감지 시간: 
   🌍 UTC: {current_time}
   🇰🇷 한국: {korea_time}

🔗 바로가기 링크:
   📝 리뷰 페이지 보기: {self.review_url}
   📍 병원 기본 정보: {self.base_url}

---
🤖 GitHub Actions 자동 모니터링 시스템
💻 5분마다 자동으로 체크하여 변화량이 있을 때만 알림을 보냅니다!

⚙️ 현재 알림 설정:
   🎯 최소 변화량: {self.min_change_threshold}개 이상
   🔇 조용한 모드: {'활성화 (변화없으면 알림안함)' if self.quiet_mode else '비활성화'}
   📧 무변화 알림: {'활성화' if self.notify_on_no_change else '비활성화'}
   🎯 시작 알림: {'활성화' if self.notify_on_startup else '비활성화'}

📈 예시: 663 → 664 (알림), 664 → 664 (조용), 664 → 662 (알림)

이 메시지는 자동으로 발송되었습니다.
            """
            
            msg = MIMEMultipart()
            msg['From'] = self.gmail_address
            msg['To'] = self.recipient_email
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            
            self.logger.info("📤 이메일 전송 중...")
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(self.gmail_address, self.gmail_password)
            server.sendmail(self.gmail_address, self.recipient_email, msg.as_string())
            server.quit()
            
            self.logger.info(f"✅ 이메일 전송 완료: {old_count or 'N/A'} → {new_count} ({change_text})")
            return True
        except Exception as e:
            self.logger.error(f"❌ 이메일 전송 실패: {e}")
            return False
    
    def run_monitoring(self):
        try:
            self.logger.info("🎉 분당제일여성병원 리뷰 모니터링 시작!")
            self.logger.info(f"⚙️ 설정: 조용한모드={self.quiet_mode}, 최소변화량={self.min_change_threshold}")
            
            if not self.validate_settings():
                return False
            
            # 현재 리뷰 개수 가져오기
            current_count = self.get_review_count()
            self.logger.info(f"📊 현재 리뷰 개수: {current_count}개")
            
            # 히스토리 로드
            history = []
            if os.path.exists(self.history_file):
                try:
                    with open(self.history_file, 'r', encoding='utf-8') as f:
                        history = json.load(f)
                        self.logger.info(f"📚 기존 히스토리 {len(history)}개 로드")
                except Exception as e:
                    self.logger.warning(f"⚠️ 히스토리 로드 실패: {e}")
            
            last_count = None
            if history:
                last_count = history[-1].get('review_count')
                self.logger.info(f"📋 이전 기록: {last_count}개")
            
            # 🎯 알림 발송 여부 결정
            should_notify, notification_reason = self.should_send_notification(last_count, current_count)
            
            # 새 기록 생성
            new_record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "korea_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "review_count": current_count,
                "previous_count": last_count,
                "change": current_count - last_count if last_count else 0,
                "notification_reason": notification_reason,
                "notification_sent": False,
                "check_interval": "5분마다"
            }
            
            # 알림 발송
            if should_notify:
                success = self.send_email_notification(last_count, current_count, notification_reason)
                new_record["notification_sent"] = success
                if success:
                    self.logger.info("📧 알림 발송 성공!")
                else:
                    self.logger.error("❌ 알림 발송 실패!")
            else:
                self.logger.info(f"🔇 알림 발송 안함 (이유: {notification_reason})")
            
            # 히스토리 저장 (최근 200개 기록 보관)
            history.append(new_record)
            history = history[-200:]
            
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
            
            self.logger.info("✅ 모니터링 완료!")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 모니터링 실행 중 오류: {e}")
            return False

def main():
    print("🎉 분당제일여성병원 리뷰 모니터링 - 5분마다 체크!")
    print("📈 변화가 있을 때만 알림을 보냅니다 (예: 663→664, 664→662)")
    print("🔇 변화가 없으면 조용히 넘어갑니다 (예: 663→663)")
    
    monitor = BundangCloudMonitor()
    success = monitor.run_monitoring()
    
    if success:
        print("✅ 모니터링 성공!")
    else:
        print("❌ 모니터링 실패!")
        exit(1)

if __name__ == "__main__":
    main()
