# goose-lab: sandboxed data-analysis + media toolchain for Goose.
# Python REPL server (persistent state) on port 8800 inside the container, plus yt-dlp and ffmpeg for media work.
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1 MPLBACKEND=Agg PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg fonts-dejavu-core fonts-liberation libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi8 libjpeg62-turbo \
      libcairo2 shared-mime-info ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip && pip install \
      numpy pandas polars pyarrow duckdb scipy statsmodels scikit-learn \
      matplotlib seaborn plotly kaleido \
      openpyxl xlsxwriter xlrd odfpy python-docx python-pptx \
      weasyprint markdown pygments tabulate jinja2 \
      pillow imageio requests beautifulsoup4 lxml \
      yt-dlp

RUN useradd -m -u 1000 lab
COPY lab_server.py /opt/lab/lab_server.py
COPY goose_style.py /opt/lab/goose_style.py
COPY report.css /opt/lab/report.css
USER lab
WORKDIR /work
EXPOSE 8800
CMD ["python", "/opt/lab/lab_server.py"]
