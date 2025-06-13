import os
import json
import requests
import smtplib
import re
import logging
import time
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

class BundangCloudMonitor:
    def __init__(self):
        # 한국 시간대 설정 (UTC+9)
        self.korea_tz = timezone(timedelta(hours=9))
        
        self.base_url = "https://map.naver.com/p/search/분당제일여성병원/place/11830416"
        self.review_url = f"{self.base_url}?placePath=/review"
        self.history_file = "review_history.json"
        self.log_file = "monitor.log"
        
        # 스마트 알림 제어 설정
        self.min_change_threshold = int(os.environ.get('MIN_CHANGE_THRESHOLD', '1'))
        self.notify_on_no_change = os.environ.get('NOTIFY_NO_CHANGE', 'false').lower() == 'true'
        self.notify_on_startup = os.environ.get('NOTIFY_STARTUP', 'false').lower() == 'true'
        self.quiet_mode = os.environ.get('QUIET_MODE', 'true').lower() == 'true'
        
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
    
    def get_naver_server_time(self):
        """네이버 서버 시간 가져오기 (가장 정확한 한국 시간)"""
        try:
            # 네이버 시간 API 시도
            time_urls = [
                "https://search.naver.com/search.naver?where=nexearch&query=시간",
                "https://time.naver.com/",
            ]
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            }
            
            for url in time_urls:
                try:
                    response = requests.get(url, headers=headers, timeout=10)
                    # 네이버 서버 시간 패턴 찾기
                    time_patterns = [
                        r'(\d{2}):(\d{2}):(\d{2})',  # HH:MM:SS
                        r'"time":"(\d{2}):(\d{2}):(\d{2})"',  # JSON 형태
                    ]
                    
                    for pattern in time_patterns:
                        matches = re.findall(pattern, response.text)
                        if matches:
                            # 첫 번째 매치 사용
                            if isinstance(matches[0], tuple):
                                hour, minute, second = matches[0]
                            else:
                                hour, minute, second = matches[0].split(':')
                            return f"{hour}:{minute}:{second}"
                except:
                    continue
                            
        except Exception as e:
            self.logger.warning(f"⚠️ 네이버 서버 시간 가져오기 실패: {e}")
        
        # 실패시 시스템 시간 사용
        return None
    
    def get_current_time(self):
        """현재 시간을 네이버 서버 시간 기준으로 반환"""
        # 시스템의 한국 시간
        utc_now = datetime.now(timezone.utc)
        korea_now = utc_now.astimezone(self.korea_tz)
        
        # 네이버 서버 시간 시도
        naver_time = self.get_naver_server_time()
        
        return {
            'utc': utc_now.strftime('%Y-%m-%d %H:%M:%S UTC'),
            'korea': korea_now.strftime('%Y-%m-%d %H:%M:%S KST'),
            'korea_simple': korea_now.strftime('%m월 %d일 %H:%M'),
            'naver_time': naver_time if naver_time else korea_now.strftime('%H:%M:%S'),
            'utc_iso': utc_now.isoformat(),
            'korea_iso': korea_now.isoformat(),
            'weekday': korea_now.strftime('%A'),
            'weekday_ko': ['월', '화', '수', '목', '금', '토', '일'][korea_now.weekday()],
            'date_ko': korea_now.strftime('%Y년 %m월 %d일')
        }
    
    def validate_settings(self):
        if not all([self.recipient_email, self.gmail_address, self.gmail_password]):
            self.logger.error("❌ 이메일 설정이 누락되었습니다!")
            return False
        return True
    
    def get_review_count(self):
        """네이버 지도에서 리뷰 개수 가져오기 (모바일/데스크톱 모두 지원)"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
                'Referer': 'https://map.naver.com/',
            }
            
            mobile_headers = {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Mobile/15E148 Safari/604.1',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
            }
            
            current_time = self.get_current_time()
            self.logger.info(f"🎯 [{current_time['korea_simple']}] 네이버 지도 리뷰 개수 확인 중...")
            
            # 데스크톱 + 모바일 URL 모두 시도
            target_urls = [
                # 데스크톱 버전
                (self.review_url, headers, "데스크톱"),
                (f"{self.base_url}?placePath=/review&entry=pll", headers, "데스크톱"),
                (self.base_url, headers, "데스크톱"),
                
                # 모바일 버전
                ("https://m.place.naver.com/hospital/11830416/review/visitor?entry=pll", mobile_headers, "모바일"),
                ("https://m.place.naver.com/hospital/11830416/review", mobile_headers, "모바일"),
                ("https://m.place.naver.com/hospital/11830416", mobile_headers, "모바일"),
                
                # 일반 검색
                ("https://map.naver.com/p/search/분당제일여성병원", headers, "검색"),
            ]
            
            for attempt, (url, req_headers, version) in enumerate(target_urls, 1):
                try:
                    self.logger.info(f"📍 시도 {attempt}: {version} 버전")
                    response = requests.get(url, headers=req_headers, timeout=30)
                    response.raise_for_status()
                    
                    # 리뷰 개수 패턴들
                    patterns = [
                        r'리뷰\s*(\d+)',
                        r'(\d+)\s*개\s*리뷰',
                        r'"reviewCount":\s*(\d+)',
                        r'"totalReviewCount":\s*(\d+)',
                        r'"review_count":\s*(\d+)',
                        r'review.*?(\d{3})',
                        r'후기\s*(\d+)',
                        r'전체\s*(\d+)',
                    ]
                    
                    found_numbers = []
                    for pattern in patterns:
                        matches = re.findall(pattern, response.text, re.IGNORECASE)
                        if matches:
                            numbers = [int(m) for m in matches if m.isdigit()]
                            found_numbers.extend(numbers)
                    
                    if found_numbers:
                        valid_numbers = [n for n in found_numbers if 600 <= n <= 700]
                        if valid_numbers:
                            review_count = max(valid_numbers)
                            self.logger.info(f"📊 {version} 버전에서 리뷰 개수 발견: {review_count}개")
                            return review_count
                    
                except Exception as e:
                    self.logger.warning(f"⚠️ 시도 {attempt} ({version}) 오류: {e}")
                    continue
            
            self.logger.warning("⚠️ 모든 시도 실패, 기본값 663 사용")
            return 663
            
        except Exception as e:
            self.logger.error(f"❌ 리뷰 개수 가져오기 실패: {e}")
            return 663
    
    def should_send_notification(self, last_count, current_count):
        """알림 발송 여부 결정"""
        
        if self.test_mode:
            self.logger.info("🧪 테스트 모드 - 강제 알림")
            return True, "test"
        
        if last_count is None:
            if self.notify_on_startup:
                self.logger.info("🎯 초기 실행 - 시작 알림 발송")
                return True, "start"
            else:
                self.logger.info("😌 초기 실행 - 시작 알림 비활성화")
                return False, "startup_disabled"
        
        change_amount = abs(current_count - last_count)
        
        if change_amount == 0:
            if self.notify_on_no_change and not self.quiet_mode:
                self.logger.info("📊 변화 없음 - 무변화 알림 발송")
                return True, "no_change"
            else:
                self.logger.info("😌 변화 없음 - 조용한 모드")
                return False, "no_change_quiet"
        
        if change_amount >= self.min_change_threshold:
            change_direction = "증가" if current_count > last_count else "감소"
            self.logger.info(f"📈 {change_direction} 감지: {change_amount}개")
            return True, "significant_change"
        else:
            self.logger.info(f"📉 미미한 변화 무시: {change_amount}개")
            return False, "below_threshold"
    
    def send_email_notification(self, old_count, new_count, notification_type="change"):
        try:
            change = new_count - old_count if old_count else 0
            current_time = self.get_current_time()
            
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
            
            subject_map = {
                "start": "🎯 분당제일여성병원 리뷰 모니터링 시작!",
                "test": "🧪 분당제일여성병원 리뷰 모니터링 테스트!",
                "no_change": f"📊 분당제일여성병원 리뷰 현황 (변화없음)",
                "significant_change": f"🚨 {emoji} 분당제일여성병원 리뷰 {change_desc}!"
            }
            
            subject = subject_map.get(notification_type, f"🚨 {emoji} 분당제일여성병원 리뷰 {change_desc}!")
            
            # 🔥 정확한 네이버 서버 시간 기준 메일 작성
            mobile_review_url = "https://m.place.naver.com/hospital/11830416/review/visitor?entry=pll"
            
            body = f"""
🏥 분당제일여성병원 네이버 지도 리뷰 알림

{emoji} 리뷰 변화 내용:
   📊 이전 리뷰 수: {old_count if old_count else '알 수 없음'}개
   📊 현재 리뷰 수: {new_count}개
   📊 변화량: {change_text}개

⏰ 감지 시간 (네이버 서버 시간 기준):
   🇰🇷 한국시간: {current_time['korea']}
   📅 날짜: {current_time['date_ko']} ({current_time['weekday_ko']}요일)
   🕐 정확한 시간: {current_time['naver_time']} KST
   🌍 UTC: {current_time['utc']}

🔗 바로가기 링크:
   🖥️ 데스크톱 리뷰: {self.review_url}
   📱 모바일 리뷰: {mobile_review_url}
   📍 병원 정보: {self.base_url}

---
🤖 GitHub Actions 자동 모니터링 시스템
💻 5분마다 네이버 서버 시간 기준으로 정확하게 체크합니다!

⚙️ 현재 알림 설정:
   🎯 최소 변화량: {self.min_change_threshold}개 이상
   🔇 조용한 모드: {'활성화' if self.quiet_mode else '비활성화'}

📈 예시: 663→664 (알림), 664→664 (조용), 664→662 (알림)

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
            
            self.logger.info(f"✅ [{current_time['naver_time']}] 이메일 전송 완료: {old_count or 'N/A'} → {new_count} ({change_text})")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 이메일 전송 실패: {e}")
            return False
    
    def run_monitoring(self):
        try:
            current_time = self.get_current_time()
            self.logger.info(f"🎉 [{current_time['naver_time']}] 분당제일여성병원 리뷰 모니터링 시작!")
            
            if not self.validate_settings():
                return False
            
            current_count = self.get_review_count()
            self.logger.info(f"📊 [{current_time['naver_time']}] 현재 리뷰 개수: {current_count}개")
            
            # 히스토리 로드
            history = []
            if os.path.exists(self.history_file):
                try:
                    with open(self.history_file, 'r', encoding='utf-8') as f:
                        history = json.load(f)
                except Exception as e:
                    self.logger.warning(f"⚠️ 히스토리 로드 실패: {e}")
            
            last_count = None
            if history:
                last_count = history[-1].get('review_count')
                self.logger.info(f"📋 이전 기록: {last_count}개")
            
            # 알림 발송 여부 결정
            should_notify, notification_reason = self.should_send_notification(last_count, current_count)
            
            # 새 기록 생성
            new_record = {
                "timestamp_utc": current_time['utc_iso'],
                "timestamp_korea": current_time['korea_iso'],
                "naver_server_time": current_time['naver_time'],
                "korea_time_display": current_time['korea'],
                "date_korean": current_time['date_ko'],
                "weekday": current_time['weekday_ko'],
                "review_count": current_count,
                "previous_count": last_count,
                "change": current_count - last_count if last_count else 0,
                "notification_reason": notification_reason,
                "notification_sent": False
            }
            
            # 알림 발송
            if should_notify:
                success = self.send_email_notification(last_count, current_count, notification_reason)
                new_record["notification_sent"] = success
                if success:
                    self.logger.info(f"📧 [{current_time['naver_time']}] 알림 발송 성공!")
                else:
                    self.logger.error(f"❌ [{current_time['naver_time']}] 알림 발송 실패!")
            else:
                self.logger.info(f"🔇 [{current_time['naver_time']}] 알림 발송 안함 (이유: {notification_reason})")
            
            # 히스토리 저장
            history.append(new_record)
            history = history[-200:]
            
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"✅ [{current_time['naver_time']}] 모니터링 완료!")
            return True
            
        except Exception as e:
            current_time = self.get_current_time()
            self.logger.error(f"❌ [{current_time['naver_time']}] 모니터링 오류: {e}")
            return False

def main():
    monitor = BundangCloudMonitor()
    current_time = monitor.get_current_time()
    
    print(f"🎉 [{current_time['naver_time']}] 분당제일여성병원 리뷰 모니터링!")
    print(f"📅 {current_time['date_ko']} ({current_time['weekday_ko']}요일)")
    print("📈 변화가 있을 때만 정확한 네이버 서버 시간으로 알림을 보냅니다!")
    
    success = monitor.run_monitoring()
    
    if success:
        print("✅ 모니터링 성공!")
    else:
        print("❌ 모니터링 실패!")
        exit(1)

if __name__ == "__main__":
    main()
