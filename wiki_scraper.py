import os
from airflow.models import DAG, Variable
from airflow.operators.dummy_operator import DummyOperator
from airflow.operators.python_operator import PythonOperator
from airflow.operators.bash_operator import BashOperator
from airflow.contrib.operators.bigquery_operator import BigQueryOperator
from airflow.contrib.operators.bigquery_check_operator import BigQueryCheckOperator
from airflow.providers.google.cloud.transfers.gcs_to_bigquery import GCSToBigQueryOperator
from airflow.utils.dates import days_ago
from datetime import timedelta 
from functools import partial
import json
import time
import urllib.parse
import urllib.request
import urllib.error
import logging
from datetime import date, timedelta
from typing import Final as Const

log = logging.getLogger(__name__)
log.setLevel('DEBUG')

################################
# config start #################
################################

GCS_BUCKET = Variable.get("gcs_bucket")
GCP_PROJECT = Variable.get("gcp_project")
INGESTION_DATASET = 'bright_data_ingestion'

################################
# config end ###################
################################

args = {
    'start_date': days_ago(2),
    'project_id': Variable.get('gcp_project'),
    'retry_delay': timedelta(minutes=1),
    'depends_on_past': False
}

dag = DAG(
    schedule_interval='0 12 * * *',
    # schedule_interval=None,
    dag_id=os.path.basename(__file__),
    default_args=args,
    concurrency=1,
    catchup=False,
    tags = ['scraping']
)

########################################
# DUMMY OPERATORS ######################
########################################

start = DummyOperator(task_id='start', dag=dag)
end = DummyOperator(task_id='end', dag=dag)

########################################
# OPERATORS ############################
########################################

# region Config
# Output
OUT_FORMAT: Const = "json"
OUT_DIR: Const = "wiki/"
START_DATE: Const = "20231001"

# Misc
# UPDATE_TIME: Const = "12:00"
articles = (
    ("Hamas", "en"),
    ("Palestinian_Islamic_Jihad", "en")
)
#     ("����", "he"),
#     ("��'����_�������_��������", "he")
# endregion

def to_timestamp(date: date):
    log.info(f'**{to_timestamp.__name__}**')
    return f"{date.year}{date.month}{date.day}"


def get_page_data(article_name_: str, end_date: str, start_date: str = START_DATE, lang: str = "en") -> ():
    log.info(f'**{get_page_data.__name__}**')
    """
    Extract information and statistics about a certain page of the Wikipedia, from a certain date(s).

    :param article_name_: Title of Wiki entry page.
    :param end_date: Date after which to stop providing data; Format: "yyyymmdd", e.g "20230225" (25.2.2023).
    :param start_date: Date from which to start providing data; Format: "yyyymmdd", e.g "20230225" (25.2.2023).
    :param lang: Language of wiki page (e.g "en", "he", "ru").
    :return: Tuple of data dictionaries for each day checked.
    """

    url = u"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/" \
          u"{}.wikipedia.org/all-access/all-agents/{}/daily/{}/{}" \
        .format(lang.lower(), urllib.parse.quote(article_name_), start_date, end_date)

    try:
        page = urllib.request.urlopen(url).read()
    except urllib.error.URLError:
        log.info("Update failed, No internet connection")
        return

    page = page.decode("UTF-8")
    items = tuple(json.loads(page)["items"])
    return items


def update_daily_data():
    log.info(f'**{update_daily_data.__name__}**')
    log.info(f"The time is {time.asctime()}, Updating data...")
    yesterday: str = to_timestamp(date.today() - timedelta(1))

    for article in articles:
        article_name, article_lang = article
        article_page_data = get_page_data(article_name, yesterday, lang=article_lang)

        if article_page_data is None:
            break

        if not os.path.exists(OUT_DIR + article_name):
            os.makedirs(OUT_DIR + article_name)

        for daily_stats in article_page_data:
            with open(f"{OUT_DIR + article_name}/{daily_stats['timestamp']}.{OUT_FORMAT}", 'w') as out_file:
                json.dump(daily_stats, out_file)

        log.info(f"Written JSON for '{article_name} (data for {len(article_page_data)} dates)'")

########################################
# OPERATORS ############################
########################################

OP_update_daily_data = PythonOperator(
    task_id='OP_update_daily_data',
    python_callable=update_daily_data,
    retries=1,
    dag=dag
)

OP_load_wiki2gcs = BashOperator(
    task_id='OP_load_wiki2gcs',
    bash_command=f"gsutil cp -r /home/omid/wiki/ gs://{GCS_BUCKET}/;",
    retries=1,
    dag=dag
)

########################################
# FLOW #################################
########################################

start >> OP_update_daily_data >> OP_load_wiki2gcs >> end


if __name__ == "__main__":
    schedule.every().day.at(UPDATE_TIME).do(update_daily_data)
    update_daily_data()

    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        print("Shutdown")