from flask import Flask, render_template, request, jsonify, redirect, url_for
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ConnectionError
import mysql.connector
from mysql.connector import Error
import logging

app = Flask(__name__)

# MySQL Configuration
mysql_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '12345678',
    'database': 'practo_clone'
}

# Elasticsearch Configuration
es = Elasticsearch(["http://localhost:9200"])

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def is_elasticsearch_running():
    try:
        return es.ping()
    except Exception as e:
        logger.error(f"Elasticsearch connection failed! {e}")
        return False

def create_search_indices():
    try:
        index_name = "doctors"
        if not es.indices.exists(index=index_name):
            doctors_mapping = {
                "mappings": {
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {
                            "type": "text",
                            "fields": {
                                "completion": {"type": "completion"}  
                            }
                        },
                        "specialization": {
                            "type": "text",
                            "fields": {
                                "completion": {"type": "completion"}  
                            }
                        },
                        "hospital_id": {"type": "integer"},
                        "experience_years": {"type": "integer"},
                        "location": {"type": "text"},
                        "phone": {"type": "text"}  
                    }
                }
            }
            es.indices.create(index=index_name, body=doctors_mapping)
            logger.info(f"Successfully created index: {index_name}")
        else:
            logger.info(f"Index '{index_name}' already exists.")
    except ConnectionError as e:
        logger.error(f"Elasticsearch connection error while creating '{index_name}' index: {e}")
    except Exception as e:
        logger.error(f"Error creating '{index_name}' index: {e}")

    try:
        index_name = "hospitals"
        if not es.indices.exists(index=index_name):
            hospitals_mapping = {
                "mappings": {
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {
                            "type": "text",
                            "fields": {
                                "keyword": {"type": "keyword"},
                                "completion": {"type": "completion"}
                            }
                        },
                        "location": {"type": "text"},
                        "contact": {"type": "keyword"}
                    }
                }
            }
            es.indices.create(index=index_name, body=hospitals_mapping)
            logger.info(f"Successfully created index: {index_name}")
        else:
            logger.info(f"Index '{index_name}' already exists.")
    except ConnectionError as e:
        logger.error(f"Elasticsearch connection error while creating '{index_name}' index: {e}")
    except Exception as e:
        logger.error(f"Error creating '{index_name}' index: {e}")


def index_doctors():
    if not is_elasticsearch_running():
        logger.warning("Elasticsearch is not running. Skipping indexing.")
        return
    try:
        with mysql.connector.connect(**mysql_config) as conn, conn.cursor(dictionary=True) as cursor:
            cursor.execute("""
                SELECT d.*, h.name AS hospital_name 
                FROM doctors d 
                LEFT JOIN hospitals h ON d.hospital_id = h.id
            """)
            doctors = cursor.fetchall()
            for doctor in doctors:
                es.index(index="doctors", id=doctor['id'], document=doctor)
            logger.info(f"Indexed {len(doctors)} doctors into Elasticsearch.")
    except Error as e:
        logger.error(f"MySQL Error: {e}")

def index_hospitals():
    if not is_elasticsearch_running():
        logger.warning("Elasticsearch is not running. Skipping indexing.")
        return
    try:
        with mysql.connector.connect(**mysql_config) as conn, conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM hospitals")
            hospitals = cursor.fetchall()
            for hospital in hospitals:
                es.index(index="hospitals", id=hospital['id'], document=hospital)
            logger.info(f"Indexed {len(hospitals)} hospitals into Elasticsearch.")
    except Error as e:
        logger.error(f"MySQL Error: {e}")

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('q', '')
    if not query:
        return jsonify({"doctors": [], "hospitals": []})
    if not is_elasticsearch_running():
        return jsonify({"error": "Elasticsearch is not running"}), 500
    try:
        doctor_results = es.search(index="doctors", body={
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": ["name^3", "specialization^2"],
                    "fuzziness": "AUTO"
                }
            }
        })
        hospital_results = es.search(index="hospitals", body={
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": ["name^3", "location"],
                    "fuzziness": "AUTO"
                }
            }
        })
        doctors = [{"id": hit["_source"]["id"], "name": hit["_source"]["name"], "specialization": hit["_source"]["specialization"], "type": "doctor"} for hit in doctor_results["hits"]["hits"]]
        hospitals = [{"id": hit["_source"]["id"], "name": hit["_source"]["name"], "location": hit["_source"]["location"], "type": "hospital"} for hit in hospital_results["hits"]["hits"]]
        return jsonify({"doctors": doctors, "hospitals": hospitals})
    except Exception as e:
        logger.error(f"Search error: {e}")
        return jsonify({"error": "Search failed"}), 500
@app.route('/doctors')
def doctors_list():
    try:
        with mysql.connector.connect(**mysql_config) as conn, conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT DISTINCT specialization FROM doctors")
            specializations = [row['specialization'] for row in cursor.fetchall()]

            cursor.execute("""
                SELECT doctors.*, hospitals.name AS hospital_name, hospitals.id AS hospital_id
                FROM doctors
                LEFT JOIN hospitals ON doctors.hospital_id = hospitals.id
                ORDER BY doctors.name ASC
            """)
            doctors = cursor.fetchall()

        return render_template('doctors.html', doctors=doctors, specializations=specializations)

    except Error as e:
        print(f" MySQL Error: {e}")
        return "An error occurred while fetching doctors", 500

@app.route('/doctors/<int:doctor_id>')
def doctor_details(doctor_id):
    try:
        with mysql.connector.connect(**mysql_config) as conn, conn.cursor(dictionary=True) as cursor:
            cursor.execute("""
                SELECT doctors.*, hospitals.name AS hospital_name, hospitals.location, hospitals.contact 
                FROM doctors
                LEFT JOIN hospitals ON doctors.hospital_id = hospitals.id
                WHERE doctors.id = %s
            """, (doctor_id,))
            doctor = cursor.fetchone()

        if doctor:
            return render_template('doctor_details.html', doctor=doctor)
        else:
            return "Doctor not found", 404

    except Error as e:
        print(f" MySQL Error: {e}")
        return "An error occurred while fetching doctor details"

@app.route('/hospitals')
def hospitals_list():
    try:
        with mysql.connector.connect(**mysql_config) as conn, conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM hospitals ORDER BY name ASC")
            hospitals = cursor.fetchall()

        return render_template('hospital.html', hospitals=hospitals)

    except Error as e:
        print(f" MySQL Error: {e}")
        return "An error occurred", 500

@app.route('/hospitals/<int:hospital_id>')
def hospital_details(hospital_id):
    try:
        with mysql.connector.connect(**mysql_config) as conn, conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM hospitals WHERE id = %s", (hospital_id,))
            hospital = cursor.fetchone()

            cursor.execute("SELECT * FROM doctors WHERE hospital_id = %s", (hospital_id,))
            doctors = cursor.fetchall()

        if hospital:
            return render_template('hospital_details.html', hospital=hospital, doctors=doctors)
        else:
            return "Hospital not found", 404

    except Error as e:
        print(f" MySQL Error: {e}")
        return "An error occurred while fetching hospital details"

# Admin routes
@app.route('/admin')
def admin_dashboard():
    return render_template('admin_dashboard.html')

@app.route('/admin/doctors')
def admin_doctors():
    try:
        with mysql.connector.connect(**mysql_config) as conn, conn.cursor(dictionary=True) as cursor:
            cursor.execute("""
                SELECT doctors.*, hospitals.name AS hospital_name
                FROM doctors
                LEFT JOIN hospitals ON doctors.hospital_id = hospitals.id
                ORDER BY doctors.name ASC
            """)
            doctors = cursor.fetchall()
            
            cursor.execute("SELECT id, name FROM hospitals ORDER BY name ASC")
            hospitals = cursor.fetchall()
            
        return render_template('admin_doctors.html', doctors=doctors, hospitals=hospitals)
    
    except Error as e:
        print(f" MySQL Error: {e}")
        return "An error occurred", 500

@app.route('/admin/add_doctor', methods=['POST'])
def add_doctor():
    if request.method == 'POST':
        name = request.form.get('name')
        specialization = request.form.get('specialization')
        hospital_id = request.form.get('hospital_id')
        experience_years = request.form.get('experience_years')
        location = request.form.get('location')
        phone = request.form.get('phone')
        
        try:
            with mysql.connector.connect(**mysql_config) as conn, conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO doctors (name, specialization, hospital_id, experience_years, location, phone)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (name, specialization, hospital_id, experience_years, location, phone))
                conn.commit()
                
                if is_elasticsearch_running():
                    index_doctors()
                
            return redirect('/admin/doctors')
        
        except Error as e:
            print(f" MySQL Error: {e}")
            return "An error occurred while adding doctor", 500

@app.route('/admin/hospitals')
def admin_hospitals():
    try:
        with mysql.connector.connect(**mysql_config) as conn, conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM hospitals ORDER BY name ASC")
            hospitals = cursor.fetchall()

            if is_elasticsearch_running():
                index_doctors()
            
        return render_template('admin_hospitals.html', hospitals=hospitals)
    
    except Error as e:
        print(f" MySQL Error: {e}")
        return "An error occurred", 500

@app.route('/admin/add_hospital', methods=['POST'])
def add_hospital():
    if request.method == 'POST':
        name = request.form.get('name')
        location = request.form.get('location')
        contact = request.form.get('contact')
        
        try:
            with mysql.connector.connect(**mysql_config) as conn, conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO hospitals (name, location, contact)
                    VALUES (%s, %s, %s)
                """, (name, location, contact))
                conn.commit()
                
            return redirect('/admin/hospitals')
        
        except Error as e:
            print(f"MySQL Error: {e}")
            return "An error occurred while adding hospital", 500

if __name__ == '__main__':
    try:
        if is_elasticsearch_running():
            logger.info("Setting up Elasticsearch...")
            create_search_indices()
            index_doctors()
            index_hospitals()
        else:
            logger.warning("Skipping Elasticsearch setup as it is not running.")
    except Exception as e:
        logger.error(f"Error during startup: {e}")
    logger.info("Starting Flask server...")
    app.run(debug=True)
