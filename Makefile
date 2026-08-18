.PHONY: run test lint install clean

# تثبيت المتطلبات
install:
	pip install -r requirements.txt

# تشغيل المشروع محلياً
run:
	python src/main.py

# تشغيل الاختبارات
test:
	python -m pytest tests/ -v

# فحص جودة الكود
lint:
	python -m flake8 src/ tests/ --max-line-length=100

# تنظيف ملفات Python المؤقتة
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; \
	find . -type f -name "*.pyc" -delete 2>/dev/null; \
	echo "Cleaned."

# عرض المتغيرات البيئية المطلوبة
env-check:
	@echo "Required environment variables:"
	@echo "  FPL_TEAM_ID"
	@echo "  TELEGRAM_BOT_TOKEN"
	@echo "  TELEGRAM_CHAT_ID"
	@echo "  INJURY_SOURCE_URL (optional)"
	@echo "  TOP_N_MANAGERS (optional, default=10)"
