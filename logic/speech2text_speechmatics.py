import codecs
import json
import logging
import time
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
import requests

CONFIG_FILE = './keys/speechmatics_config.json'


class SpeechmaticsConfig:
    def __init__(self, userId, apiAuthToken, language='en-US', format='txt', text=None, callback_url=None, notification=None, notification_email=None):

        if not userId:
            raise Exception('required userId is empty')
        self.userId = userId

        if not apiAuthToken:
            raise Exception('required apiAuthToken is empty')
        self.apiAuthToken = apiAuthToken

        if not language:
            raise Exception('required language is empty')
        self.language = language
        
        if not format:
            raise Exception('required format is empty')
        self.format = format

        self.text = text
        self.callback_url = callback_url
        self.notification = notification
        self.notification_email = notification_email


    @classmethod
    def from_json(cls, file_name):
        loaded_json = {}
        with open(file_name, 'r') as f:
            loaded_json = json.load(f)
        return cls(**loaded_json)


class SpeechmaticsError(Exception):
    """
    For errors that are specific to Speechmatics systems and pipelines.
    """

    def __init__(self, msg, returncode=1):
        super(SpeechmaticsError, self).__init__(msg)
        self.msg = msg
        self.returncode = returncode

    def __str__(self):
        return self.msg


class SpeechmaticsClient(object):
    """
    A simple client to interact with the Speechmatics REST API
    Documentation at https://app.speechmatics.com/api-details
    """

    def __init__(self, api_user_id, api_token, base_url='https://api.speechmatics.com/v1.0'):
        self.api_user_id = api_user_id
        self.api_token = api_token
        self.base_url = base_url

    def job_post(self, audio, lang, text=None, callback_url=None, notification=None, notification_email=None):
        """
        Upload a new audio file to speechmatics for transcription
        If text file is specified upload that as well for an alignment job
        If upload suceeds then this method will return the id of the new job
        If succesful returns an integer representing the job id
        """

        url = "".join([self.base_url, '/user/', self.api_user_id, '/jobs/'])
        params = {'auth_token': self.api_token}
        try:
            files = {'data_file': open(audio, "rb")}
        except IOError as ex:
            logging.error("Problem opening audio file {}".format(audio))
            raise

        if text:
            try:
                files['text_file'] = open(text, "rb")
            except IOError as ex:
                logging.error("Problem opening text file {}".format(text))
                raise

        data = {"model": lang}
        if "=" in data['model']:
            (data['model'], data['version']) = data['model'].split('=', 1)

        if notification:
            data['notification'] = notification
            if notification == 'callback':
                data['callback'] = callback_url
        if notification_email:
            data['notification_email_address'] = notification_email

        request = requests.post(url, data=data, files=files, params=params)
        if request.status_code == 200:
            json_out = json.loads(request.text)
            return json_out['id']
        else:
            err_msg = "Attempt to POST job failed with code {}\n".format(
                request.status_code)
            if request.status_code == 400:
                err_msg += ("Common causes of this error are:\n"
                            "Malformed arguments\n"
                            "Missing data file\n"
                            "Absent / unsupported language selection.")
            elif request.status_code == 401:
                err_msg += ("Common causes of this error are:\n"
                            "Invalid user id or authentication token.")
            elif request.status_code == 403:
                err_msg += ("Common causes of this error are:\n"
                            "Insufficient credit\n"
                            "User id not in our database\n"
                            "Incorrect authentication token.")
            elif request.status_code == 429:
                err_msg += ("Common causes of this error are:\n"
                            "You are submitting too many POSTs in a short period of time.")
            elif request.status_code == 503:
                err_msg += ("Common causes of this error are:\n"
                            "The system is temporarily unavailable or overloaded.\n"
                            "Your POST will typically succeed if you try again soon.")
            err_msg += ("\nIf you are still unsure why your POST failed please contact speechmatics:"
                        "support@speechmatics.com")
            raise SpeechmaticsError(err_msg)

    def job_details(self, job_id):
        """
        Checks on the status of the given job.
        If successfuly returns a dictionary of job details.
        """
        params = {'auth_token': self.api_token}
        url = "".join([self.base_url, '/user/', self.api_user_id,
                       '/jobs/', str(job_id), '/'])
        request = requests.get(url, params=params)
        if request.status_code == 200:
            return json.loads(request.text)['job']
        else:
            err_msg = ("Attempt to GET job details failed with code {}\n"
                       "If you are still unsure why your POST failed please contact speechmatics:"
                       "support@speechmatics.com").format(request.status_code)
            raise SpeechmaticsError(err_msg)

    def get_output(self, job_id, frmat, job_type):
        """
        Downloads transcript for given transcription job.
        If successful returns the output.
        """
        params = {'auth_token': self.api_token}
        if frmat and job_type == 'transcript':
            params['format'] = 'txt'
        if frmat and job_type == 'alignment':
            params['tags'] = 'one_per_line'
        url = "".join([self.base_url, '/user/', self.api_user_id,
                       '/jobs/', str(job_id), '/', job_type])
        request = requests.get(url, params=params)
        if request.status_code == 200:
            request.encoding = 'utf-8'
            return request.text
        else:
            err_msg = ("Attempt to GET job details failed with code {}\n"
                       "If you are still unsure why your POST failed please contact speechmatics:"
                       "support@speechmatics.com").format(request.status_code)
            raise SpeechmaticsError(err_msg)

class SpeechmaticsSpeechToText:
    def __init__(self, full_path):
        self.full_path = full_path        
        self.text = ''

    def set_text(self, text):
        self.text = text

    def transcript_audio(self):
        logging.basicConfig(level=logging.INFO)

        config = SpeechmaticsConfig.from_json(CONFIG_FILE)

        logging.info(config)

        client = SpeechmaticsClient(config.userId, config.apiAuthToken)

        job_id = client.job_post(self.full_path, config.language, config.text, config.callback_url, config.notification, config.notification_email)
        logging.info("Your job has started with ID {}".format(job_id))

        details = client.job_details(job_id)

        while details[u'job_status'] not in ['done', 'expired', 'unsupported_file_format', 'could_not_align']:
            logging.info("Waiting for job to be processed.  Will check again in {} seconds".format(
                details['check_wait']))
            wait_s = details['check_wait']
            time.sleep(wait_s)
            details = client.job_details(job_id)

        if details['job_status'] == 'unsupported_file_format':
            raise SpeechmaticsError("File was in an unsupported file format and could not be transcribed. "
                                    "You have been reimbursed all credits for this job.")

        if details['job_status'] == 'could_not_align':
            raise SpeechmaticsError("Could not align text and audio file. "
                                    "You have been reimbursed all credits for this job.")

        logging.info("Processing complete, getting output")

        if details['job_type'] == 'transcription':
            job_type = 'transcript'
        elif details['job_type'] == 'alignment':
            job_type = 'alignment'
        output = client.get_output(job_id, config.format, job_type)

        logging.info("Output: {}".format(output))

        return output.encode('utf-8')

if __name__ == '__main__':
    s2t = SpeechmaticsSpeechToText('./api_uploaded_files/1_nowy dzien.mp3')
    s2t.transcript_audio()
