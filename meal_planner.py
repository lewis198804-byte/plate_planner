from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
import sqlite3
import requests
import base64
import json
from dotenv import load_dotenv
import uuid
import backup_logic
from datetime import datetime
from PIL import Image, ImageOps
import os

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}


def database_con(query):
    con = sqlite3.connect("data/database.db")
    cur = con.cursor()
    return cur.execute(query)




def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_recipe_image(uploaded_file, output_path, max_size=800):
    """Process with correct orientation."""
    img = Image.open(uploaded_file)
    
    # Fix orientation FIRST
    img = ImageOps.exif_transpose(img)
    
    # Convert if needed (after rotation)
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')
    
    # Resize & save
    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    img.save(output_path, 'JPEG', quality=85, optimize=True, subsampling=0)

def init_database():
    con = sqlite3.connect("data/database.db")
    cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS recipes (" \
    "id INTEGER PRIMARY KEY AUTOINCREMENT," \
    "name TEXT," \
    "location TEXT," \
    "page_nu INTEGER," \
    "instructions JSON," \
    "photo_path TEXT," \
    "category TEXT," \
    "tags TEXT," \
    "desc TEXT,"\
    "difficulty TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS ingredients (" \
    "id INTEGER PRIMARY KEY AUTOINCREMENT," \
    "name TEXT," \
    "recipe_id INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS apscheduler_jobs (" \
    "id VARCHAR(191) PRIMARY KEY," \
    "next_run_time FLOAT," \
    "job_state BLOB)")
    cur.execute("CREATE TABLE IF NOT EXISTS settings (" \
    "id INTEGER PRIMARY KEY AUTOINCREMENT," \
    "backup_status TEXT," \
    "backup_location INTEGER," \
    "backup_frequency INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS meal_plans (" \
    "id INTEGER PRIMARY KEY AUTOINCREMENT," \
    "monday_recipe_id INTEGER," \
    "tuesday_recipe_id INTEGER," \
    "wednesday_recipe_id INTEGER," \
    "thursday_recipe_id INTEGER," \
    "friday_recipe_id INTEGER," \
    "saturday_recipe_id INTEGER," \
    "current_plan BOOL," \
    "sunday_recipe_id INTEGER)")
    con.commit()
    con.close()
    return "database built"


load_dotenv()
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
app = Flask(__name__)
app.json.sort_keys = False


@app.route("/")
def home():
    return render_template("index.html")



@app.route("/get_settings")
def get_settings():

    con = sqlite3.connect("data/database.db")
    cur = con.cursor()
    cur.execute("SELECT * FROM settings")
    settings = cur.fetchone()
    backupDetails = backup_logic.schedulerStatus()

    
    return {"ok":"true","apiKey": OPENAI_API_KEY, "settings":settings, "backup_details": backupDetails}

@app.route("/update_settings", methods=['POST'])
def update_settings():
    con = sqlite3.connect("data/database.db")
    cur = con.cursor()
    
    if request.form['backupStatus'] == "on":
        backupDir = request.form['backupDirectory']
        direcoryCheck = backup_logic.checkBackupDir(backupDir)
        if direcoryCheck['testResult'] == True:
            backupFreq = int(request.form['backupFreq'])
            backupStatus = request.form['backupStatus']
            next_backup = backup_logic.turn_on_backups(backupFreq, backupDir)

            cur.execute("UPDATE settings SET backup_status = 'on', backup_location = ?, backup_frequency = ?",(backupDir, backupFreq))
        else:
            return {"ok": "false","error" : "<span style='color:red'>Cannot write to selected backup directory</span>"}


    elif request.form['backupStatus'] == "off":
        next_backup = backup_logic.turnOffBackups()
        cur.execute("UPDATE settings SET backup_status = 'off', backup_location = '', backup_frequency = '' ")

    con.commit()
    con.close()
    return {"ok": "true","next_backup": next_backup}

@app.route("/test_backup_dir", methods = ['POST'])
def test_backup_dir():
    testResult = backup_logic.checkBackupDir(request.form['backupDir'])
    return {"testResult" : testResult['resultText']}



@app.route("/test_api")
def test_api():
    payload = {
        'model': 'gpt-4o-mini',
        'messages': [{
            'role': 'user',
            'content': [
                {'type': 'text', 'text': '''
                    Extract as RAW JSON only with no formatting. 
                    This is a test API call sent from a python flask program to establish if the user entered 
                    API key is correct and working. If this request is successful return output 
                    will be read by a python program and should be structured as a json object as follows:
                    {
                      "ok": "true"
                    }
                    Output ONLY valid JSON. No other punctuation or whitespace
                '''}
            ]
        }],
        'max_tokens': 100,
        'temperature': 0.1
    }
    testCall = openAiRequest(payload)
    print(testCall)
    return testCall


@app.route("/add_recipe")
def add_recipe():
    return render_template("add_recipe.html")

@app.route("/recipes")
def recipes():
    return render_template("recipes.html")

@app.route("/ai_recipe_add")
def ai_recipe_add():
    return render_template("ai_recipe_add.html")

@app.route("/save_ai_recipe", methods=['POST'])
def save_ai_recipe():
    saveType = request.form['saveType']

    name = request.form['recipe_name']
    location = request.form['recipe_location']
    page = request.form['page_number']
    instructions = request.form['instructions']
    ingredients = request.form['ingredients']
    tags = request.form['tags']
    difficulty = request.form['difficulty']
    description = request.form['description']
    category = request.form['category']
  
    con = sqlite3.connect("data/database.db")
    cur = con.cursor()

    error_text = ""
    if name == "" or ingredients == "" or location == "":
        error_text = "Error: missing required field!" 

    photo = request.files.get('recipe_photo')
    if photo and photo.filename:  # Real file check
        safe_name = secure_filename(photo.filename)  
        # 2. Add unique ID BEFORE
        unique_id = str(uuid.uuid4()).replace('-', '')[:8]
        filename = f"{unique_id}_{safe_name}"  # "a1b2c3d4_recipe.jpg"
        image_filename = filename

        save_recipe_image(photo,f"static/recipe_images/{filename}")

    else:
        image_filename = "defaultImage.jpg"  # Or default image
    
    if error_text != "":
         return jsonify({"ok": False, "error": error_text})

#determine if this is an edit that is being saved 
    if saveType == "edit":

        
        recipe_id = request.form['recipe_id']
        cur.execute("UPDATE recipes SET name = ?, location = ? ,page_nu = ?,instructions = ?,difficulty = ?,category = ?, tags = ?, desc =? WHERE id = ?" ,(name, location, page,instructions,difficulty,category,tags,description,recipe_id))
        cur.execute("DELETE FROM ingredients WHERE recipe_id = ?" ,(recipe_id,))
        ingredients_strings = ingredients.split(",")
        ingredients_list = []
        
        for item in ingredients_strings:
            
            if len(item.strip()) > 0:
                this_ingredient = (item.strip(), recipe_id)
                ingredients_list.append(this_ingredient)
        
        print(ingredients_list)
        
        cur.executemany("INSERT INTO ingredients (name,recipe_id) VALUES (?,?)" , ingredients_list)
        
        if image_filename != None and image_filename != "defaultImage.jpg":
            cur.execute("UPDATE recipes SET photo_path = ? WHERE id = ?" ,(image_filename,recipe_id))

        con.commit()
        con.close()
        return jsonify({"ok": True, "success": "Recipe updated succesfully!","recipe_Id": recipe_id})
#or a new recipe being saved
    else:
        cur.execute("INSERT INTO recipes (name,location,page_nu,instructions,difficulty,category,tags,photo_path,desc) VALUES (?,?,?,?,?,?,?,?,?)" ,(name, location, page,instructions,difficulty,category,tags,image_filename,description))
    
        recipe_id = cur.lastrowid
        ingredients_strings = ingredients.split(",")
        ingredients_list = []
        
        for item in ingredients_strings:
            
            if len(item.strip()) > 0:
                this_ingredient = (item.strip(), recipe_id)
                ingredients_list.append(this_ingredient)
                
        cur.executemany("INSERT INTO ingredients (name,recipe_id) VALUES (?,?)" , ingredients_list)

        con.commit()
        recipeID = cur.lastrowid
        con.close()
        return jsonify({"ok": True, "success": "Recipe added succesfully!","recipe_Id": recipeID})

@app.route("/get_recipes", methods=['POST'])
def get_recipes():
    recipeParams = request.args.to_dict()
    print(recipeParams)

    
    orderDir = "DESC"

    if recipeParams['category'] == "all":
        category = " "
    elif recipeParams['category']  == "dessert":
        category = " WHERE category = 'dessert' "
    elif recipeParams['category']  == "dinner":
        category = " WHERE category = 'dinner' "
    elif recipeParams['category']  == "other":
        category = " WHERE category = 'other' "
    else:
        category = " "
    
    #pagination code starts
    if "paginationId" in recipeParams:
        if category == " ":
            connector = "WHERE "
        elif category != " ":
            connector = "AND "
        if "direction" in recipeParams:
            if recipeParams['direction'] == "next":
                paginationQuery = connector+"id < "+recipeParams['paginationId']+" "
            elif recipeParams['direction'] == "back":
                paginationQuery = connector+"id > "+recipeParams['paginationId']+" "
                orderDir = "ASC"
        print(paginationQuery)
    else:
        paginationQuery = ""

    con = sqlite3.connect("data/database.db")
    cur = con.cursor()
    selectQuery = "SELECT * FROM recipes"+category+""+paginationQuery+"ORDER BY id "+orderDir+" LIMIT 5"
    print(selectQuery)

    cur.execute(selectQuery)
    response = cur.fetchall()
    con.close()

    return response

@app.route("/shopping_list")
def shopping_list():

    return render_template("shopping_list.html")

@app.route("/search_recipes")
def search_recipes():
    search_term = request.args.get('q', '').strip()
    con = sqlite3.connect("data/database.db")
    cur = con.cursor()
    cur.execute("SELECT * FROM recipes WHERE name LIKE ? OR tags LIKE ?", (f'%{search_term}%',)*2)
    response = cur.fetchall()
    con.close()
    return response

@app.route("/settings")
def settings():
    
    con = sqlite3.connect("data/database.db")
    cur = con.cursor()
    con.close()
    return render_template("settings.html")


@app.route("/backupDb")
def backupDb():
    backupResult = backup_logic.backup_recipe_db()
    if backupResult == True:
        return {"ok":"true","text":"<span style='color:green'>Manual backup successful</span>"}
    else:
        return {"ok":"false","text":"<span style='color:red'>Error, backup not created</span>"}


@app.route("/get_recipe_overview/<recipe_id>", methods=['GET']) 
def get_recipe_overview(recipe_id):
    con = sqlite3.connect("data/database.db")
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    
    cur.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,))
    row = cur.fetchone()
    
    con.close()
    
    if row:
        return jsonify(dict(row)) 
    else:
        return jsonify({"error": "Recipe not found"}), 404

@app.route("/save_recipe_day_change/", methods=['POST'])
def save_recipe_day_change():
    day = request.form['dayToChange']
    newRecipe = request.form['newRecipe']
    con = sqlite3.connect("data/database.db")
    cur = con.cursor()
    cur.execute("UPDATE meal_plans SET "+day+" = ? WHERE current_plan = 1", (newRecipe,))
    con.commit()
    con.close()

    return {"success" : "ok"}

@app.route("/get_menu", methods=['POST'])
def get_menu():
    con = sqlite3.connect("data/database.db")
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    
    # Get the current plan
    days = ['monday_recipe_id', 'tuesday_recipe_id', 'wednesday_recipe_id',
            'thursday_recipe_id', 'friday_recipe_id', 'saturday_recipe_id', 'sunday_recipe_id']
    
    cur.execute("SELECT " + ", ".join(days) + " FROM meal_plans WHERE current_plan = 1")
    plan = cur.fetchone()
    
    if not plan:
        con.close()
        return jsonify({"ok": False, "error": "no plan found"})
        print("no plan")
    
    menu = []
    for day in days:
        recipe_id = plan[day]
        if recipe_id is not None:
            cur.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,))
            recipe = cur.fetchone()
            if recipe:
                menu.append({day: dict(recipe)})
                print("found recipe")
            else:
                menu.append({day: dict(id = 0, name = "no Recipe")})
                print("no recipe found")

    
    con.close()
   
    return jsonify({"ok": True, "menu": menu})


@app.route("/gen_new_meal_plan", methods=['POST'])
def gen_new_plan():
    con = sqlite3.connect("data/database.db")
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    
    if request.form["planType"] == "auto":
        cur.execute("SELECT * FROM recipes WHERE category = 'dinner' ORDER BY RANDOM() LIMIT 7 ")
        rows = cur.fetchall()
        if len(rows) < 7:
            print("not enough recipes to make a full meal plan")
            [print(row[1]) for row in rows]
            while len(rows) < 7:
                rows.append({"id": 0, "name" : "No recipe Assigned"})
            #[print(row[0]) for row in rows]
        # Convert Row → dicts for JSON
        recipes = [dict(row) for row in rows]
        
        con.close()
        return jsonify(recipes)
    #else take the params provided and apply them to each days recipe selection

    con.close()
    return "something"


@app.route("/save_new_plan", methods=['POST'])
def save_new_plan():
    print(request.form['monday_recipe_id'])
    days = ['monday_recipe_id', 'tuesday_recipe_id', 'wednesday_recipe_id',
            'thursday_recipe_id', 'friday_recipe_id', 'saturday_recipe_id', 'sunday_recipe_id']
    columns = ','.join(days)
    recipe_ids = []
    for day in request.form:
        recipe_ids.append(request.form[day])
    recipes_to_enter = ','.join(recipe_ids)    
    con = sqlite3.connect("data/database.db")
    cur = con.cursor()
    cur.execute("UPDATE meal_plans SET current_plan = 0 WHERE current_plan = 1")
    print("columns:",columns,"recipes to enter",recipes_to_enter)
    cur.execute("INSERT INTO meal_plans ("+columns+", current_plan) VALUES ("+recipes_to_enter+", 1)")
    con.commit()
    con.close()

    return {"success" : "ok"}

@app.route("/del_recipe")
def delete_recipe():
    recipe_id = request.args.get('q', '').strip()
    con = sqlite3.connect("data/database.db")
    cur = con.cursor()
    cur.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
    cur.execute("DELETE FROM ingredients WHERE recipe_id = ?",(recipe_id,))
    con.commit()
    con.close()
    return "deleted"

@app.route("/view_recipe")
def view_recipe():
    recipe_id = request.args.get('q','').strip()
    print(recipe_id)
    con = sqlite3.connect("data/database.db")
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,))
    recipe_response = cur.fetchone()
    cur.execute("SELECT * FROM ingredients WHERE recipe_id = ?", (recipe_id,))
    ingredients_response = cur.fetchall()
    con.close()
    return render_template("view_recipe.html", recipe_details = recipe_response,recipe_ingredients = ingredients_response)

@app.route("/edit_recipe")
def edit_recipe():
    recipe_id = request.args.get('q', '').strip()
    con = sqlite3.connect("data/database.db")
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,))
    recipe_response = cur.fetchone()
    cur.execute("SELECT * FROM ingredients WHERE recipe_id = ?", (recipe_id,))
    ingredients_response = cur.fetchall()
    con.close()
    ingredientsList = []
    for ingredients in ingredients_response:
        ingredientsList.append(ingredients['name'])
    ingredientString = ', '.join(ingredientsList)
    return render_template("edit_recipe.html", recipe_details = recipe_response,recipe_ingredients = ingredientString)


@app.route("/process_params", methods=['POST'])
def process_params():
    con = sqlite3.connect("data/database.db")
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    if request.form:
        #ditionary of recipes that have been pulled from db to pass to return
        grabbedRecipes = {}
        #variables to hold batch cook recipe objects if they are set (following a batch cook tag search)
        batchCookA = None
        batchCookB = None
        batchCookC = None
        
        #ids of recipes already retrieved from db, to stop duplicate recipes in 1 plan
        retrievedRecipeIds = []
        # for each select form element execute the following code block
        for param in request.form:
            batchCook = False
            mealType = "single"
            #retrieve the search term and turn it into tag format to search db table with
            searchTerm = request.form[param].strip('')
            searchTerm = '#'+searchTerm.lower().replace(" ","")
            
            # check if the term is a batch cook and make checks to see if it's the first iteration of a batch cook
            # if not the first iteration, set the grabbed recipe to the previously retrieved recipe object and 
            # skip the rest of this for loop, else set the serach term and flag as a batch cook param search
            if "batchcook" in  searchTerm:
                mealType = "batch"
                if batchCookA != None and "-a" in searchTerm:
                    grabbedRecipes[param] = dict(batchCookA)
                    grabbedRecipes[param]['mealType'] = mealType
                    continue
                elif batchCookB != None and "-b" in searchTerm:
                    grabbedRecipes[param] = dict(batchCookB)
                    grabbedRecipes[param]['mealType'] = mealType
                    continue
                elif batchCookC != None and "-c" in searchTerm:
                    grabbedRecipes[param] = dict(batchCookC)
                    grabbedRecipes[param]['mealType'] = mealType
                    continue
                else:
                    #batch cook tag picked
                    batchCookValue = searchTerm
                    searchTerm = "batchcook"
                    batchCook = True
            
            if "any" in searchTerm:
                searchTerm = "#"
                
            #count number of already retrieved recipe ids and insert appropriate number of placeholders            
            placeholders = ', '.join('?' * len(retrievedRecipeIds))
            query = f"SELECT * FROM recipes WHERE tags LIKE ? AND id NOT IN ({placeholders}) AND category = 'dinner' ORDER BY RANDOM() LIMIT 1"
            # set params for db query
            params = (f'%{searchTerm}%',) + tuple(retrievedRecipeIds)
            cur.execute(query, params)
            recipe_response = cur.fetchone()
            #if a recipe match has been found (matches tag search term and is not a duplicate already added)
            if recipe_response:
                #if the batchcook flag is up, check which batch cook iteration it is and set the variable for that iteration
                # so subsequent searches for the same batch cook iteration can automatically be set to the same recipe object
                if batchCook:
                    if "-a" in batchCookValue:
                        batchCookA = recipe_response
                    elif "-b" in batchCookValue:
                        batchCookB = recipe_response
                    elif "-c" in batchCookValue:
                        batchCookC = recipe_response

               #set grabbed recipe dictionary ket to day column name (passed by the select form element) and recipe as value
                grabbedRecipes[param] = dict(recipe_response)
                grabbedRecipes[param]['mealType'] = mealType
                #add recipe id to retrieved ids so duplicate is not selected
                retrievedRecipeIds.append(recipe_response['id'])
            else:
                    #if no recipe is found to match the search term or not enough recipes (as duplicates excluded)
                    grabbedRecipes[param] = {
                        "result": "No recipe found to match tag", 
                        "name": "No recipe found",
                        "desc": "No recipe matching the search term could be found. Maybe add some more tags or recipes?"
                        }
        con.close()
        return {"results": grabbedRecipes}


#page to show the combined ingredients needed for each recipe in the current meal plan
@app.route("/generate_shopping_list")
def generate_shopping_list():

    con = sqlite3.connect("data/database.db")
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT monday_recipe_id , tuesday_recipe_id , wednesday_recipe_id , thursday_recipe_id , friday_recipe_id , saturday_recipe_id , sunday_recipe_id FROM meal_plans WHERE current_plan = 1")
    result = cur.fetchone()
    
    ingredients = {}
    for row in result:
        cur.execute("SELECT name FROM recipes WHERE id = ?", (row,))
        nameResult = cur.fetchone()
        if nameResult is not None:
            recipeName = nameResult['name'].strip()
            thisRecipeIng = []
            cur.execute("SELECT name FROM ingredients WHERE recipe_id = ?", (row,))
            ingResult = cur.fetchall()
            for ingredient in ingResult:
                thisRecipeIng.append(ingredient['name'])
                ingredients[recipeName] = (thisRecipeIng)
        else:
            ingredients['No Meal Planned'] = (["no ingredients"])

    #print(ingredients)
    return {"result" : ingredients}
    


@app.route('/analyze-recipe', methods=['POST'])
def analyze_recipe():
    print(request.files['image'].filename)
    if request.files['image'].filename == "":
        return jsonify({'errorText': '<p>Missing image file.</p> <p>Choose an image before submitting.</p>', 'ok': 'false'}), 400
    
    # Read + encode uploaded image
    img_data = request.files['image'].read()
    img_b64 = base64.b64encode(img_data).decode()
    
    headers = {
        'Authorization': f'Bearer {OPENAI_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        'model': 'gpt-4o-mini',
        'messages': [{
            'role': 'user',
            'content': [
                {'type': 'text', 'text': '''
                    Analyze this recipe photo. Extract as RAW JSON only with no formatting. 
                    If no photo has been submitted, return RAW JSON with error stating no image submitted.
                    When describing the ingredients do not use commas within a single ingredient description as the ingredients will be split using comma as a seperator. 
                    When describing the recipe instructions use a full stop to seperate the different steps. DO NOT use any commas. String will be split using the full stop as a serperator. 
                    Any temperatures should be in celcius as i live in the UK. 
                    Generate common sense tags for the recipe using context like included ingredients, vegetarian or meaty, batch cook or single meal, fakeaway etc. Tags should be seperated by spaces, not commas
                    For the description, generate a short synopsis of the recipe, no more than 100 characters long. 
                    Output will be read by python program:
                    {
                      "recipe_name": "",
                      "ingredients": ["item qty unit"],
                      "instructions": ["step 1", "step 2"],
                      "servings": "",
                      "prep_time": "",
                      "difficulty": "easy/medium/hard",
                      "tags" : ["#related_tag #related_tag"],
                      "page_number": "",
                      "description": ""
                 
                    }
                    Output ONLY valid JSON. 
                '''},
                {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{img_b64}'}}
            ]
        }],
        'max_tokens': 800,
        'temperature': 0.1
    }
    
    response = requests.post('https://api.openai.com/v1/chat/completions', 
                           headers=headers, json=payload)
    
    if response.status_code != 200:
        return jsonify({'error': response.json()}), 500
    
    
    
    result = response.json()['choices'][0]['message']['content']

    if 'error' in result:

        return jsonify({'errorText': '<p>There was an issue analyzing the image you submitted.</p><p>Check the image and try again</p><p><small>Only pictures of recipes will be processed!</small></p>','ok': 'false','recipe': result})
    
    return jsonify({'recipe': result, 'ok' : 'true','successText':'<p>Recipe image analyzed.</p><p>Take a look at the identified details and double check for accuracy!</p>'})


def openAiRequest(payload):

    headers = {
        'Authorization': f'Bearer {OPENAI_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    response = requests.post('https://api.openai.com/v1/chat/completions', 
                           headers=headers, json=payload)
    
    if response.status_code != 200:
        return jsonify({'error': response.json()}), 500
    
    result = response.json()['choices'][0]['message']['content']

    if 'error' in result:

        return jsonify({'errorText': '<p>There was an issue analyzing the image you submitted.</p><p>Check the image and try again</p><p><small>Only pictures of recipes will be processed!</small></p>','ok': 'false','recipe': result})
    
    return jsonify(result)


def startupSettingsCheck():
    con = sqlite3.connect("data/database.db")
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    
    settingsCheck = cur.execute("SELECT * FROM settings")
    settingsRes = settingsCheck.fetchone()
    if settingsRes is not None:
        if settingsRes['backup_status'] == "on":
            res = cur.execute("SELECT * FROM apscheduler_jobs")
            result = res.fetchone()

            if result == None:
                # backups are on but there is no backup job stored in the scheduler so add a backup job record 
                backup_logic.turn_on_backups()
                print("no backup jobs in the database but backups on. added job to database")
                con.close()
            else:
                #backups are on so start scheduler
                backup_logic.start_scheduler()
                print("database backups are on!")
    else:
        #likely first running of the program so insert empty settings row
        cur.execute("INSERT INTO settings (backup_status,backup_location,backup_frequency) VALUES ('off','','')")
        con.commit()
        con.close()


if __name__ == "__main__":
    init_database()
    load_dotenv()
    startupSettingsCheck()
    app.run(debug=False, host='0.0.0.0', port=5002)  # Keep port=5002


