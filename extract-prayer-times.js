const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');
const createCsvWriter = require('csv-writer').createObjectCsvWriter;

// Configuration
const url = 'https://waterloomasjid.com/main/index.php/prayers';
const outputDir = './prayer_times';
const DEBUG = true;

// Setup logging
function log(message, level = 'info') {
  const timestamp = new Date().toISOString();
  const logMessage = `[${timestamp}] [${level.toUpperCase()}] ${message}`;
  
  console.log(logMessage);
  
  if (DEBUG) {
    fs.appendFileSync(
      path.join(outputDir, 'extraction_log.txt'), 
      logMessage + '\n',
      { flag: 'a+' }
    );
  }
}

function logError(message, error) {
  log(`${message}: ${error.message}`, 'error');
  log(`Stack trace: ${error.stack}`, 'error');
}

// Ensure output directory exists
if (!fs.existsSync(outputDir)) {
  fs.mkdirSync(outputDir, { recursive: true });
}

// Clear previous log if in debug mode
if (DEBUG) {
  fs.writeFileSync(path.join(outputDir, 'extraction_log.txt'), '');
  log(`Started extraction in DEBUG mode at ${new Date().toString()}`);
}

// Helper function to convert 12-hour to 24-hour format
function convertTo24Hour(timeStr, prayerName) {
  if (!timeStr || timeStr.trim() === '') return '';
  
  // Handle special case for Jumuah times (multiple times separated by comma)
  // Take only the first time when there are multiple (e.g., Friday prayers)
  if (timeStr.includes(',')) {
    timeStr = timeStr.split(',')[0].trim();
    log(`Found multiple times, using only the first one: ${timeStr}`);
  }

  let hours = parseInt(timeStr.split(':')[0]);
  let minutes = parseInt(timeStr.split(':')[1]);
  
  // Apply conversion rules based on prayer name and time
  if (prayerName === 'Fajr' || prayerName === 'Sunrise') {
    // Morning prayers are AM
    if (hours === 12) hours = 0;
  } else if (prayerName === 'Dhuhr' || prayerName === 'Asr') {
    // Afternoon prayers are PM
    if (hours !== 12) hours += 12;
  } else if (prayerName === 'Magrib' || prayerName === 'Isha') {
    // Evening prayers are PM
    if (hours !== 12) hours += 12;
  }
  
  // Format with leading zeros
  return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
}

async function extractPrayerTimes() {
  log('Starting prayer times extraction with Puppeteer...');
  
  let browser = null;
  
  try {
    browser = await puppeteer.launch({
      headless: "new",
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    
    const page = await browser.newPage();
    
    // Navigate to the page
    log(`Navigating to ${url}...`);
    await page.goto(url, { waitUntil: 'networkidle2', timeout: 60000 });
    
    // Wait for the prayer times table to load
    await page.waitForSelector('.prayer-timetable', { timeout: 30000 });
    log('Prayer timetable found on the page');
    
    // Take a screenshot for verification
    await page.screenshot({ path: path.join(outputDir, 'prayer_table.png') });
    
    // Extract the prayer times for the current week
    const extractedData = await page.evaluate(() => {
      const rows = Array.from(document.querySelectorAll('.row'));
      console.log(`Found ${rows.length} rows in the page`);
      
      return rows.map(row => {
        const monthyear = row.querySelector('.monthyear')?.textContent.trim() || '';
        const dateday = row.querySelector('.dateday')?.textContent.trim() || '';
        const isToday = (row.querySelector('.row-mark')?.textContent.trim() === 'Today');
        
        // Extract the date number and day name
        const dateMatch = dateday.match(/(\d+)\s+(\w+)/);
        const dayNumber = dateMatch ? parseInt(dateMatch[1]) : 0;
        const dayName = dateMatch ? dateMatch[2] : '';
        
        // Figure out which day of week (0-6, where 0 is Sunday)
        let dayOfWeek = -1;
        if (dayName === 'Sun') dayOfWeek = 0;
        else if (dayName === 'Mon') dayOfWeek = 1;
        else if (dayName === 'Tue') dayOfWeek = 2;
        else if (dayName === 'Wed') dayOfWeek = 3;
        else if (dayName === 'Thu') dayOfWeek = 4;
        else if (dayName === 'Fri') dayOfWeek = 5;
        else if (dayName === 'Sat') dayOfWeek = 6;
        
        const timeCells = Array.from(row.querySelectorAll('.time-cell'));
        const prayers = {};
        
        timeCells.forEach(cell => {
          const name = cell.querySelector('.time-name')?.textContent.trim() || '';
          const startTime = cell.querySelector('.time-start')?.textContent.trim() || '';
          const iqamahTime = cell.querySelector('.time-iqamah')?.textContent.trim() || '';
          
          if (name) {
            prayers[name] = {
              start: startTime,
              iqamah: iqamahTime
            };
          }
        });
        
        return {
          date: `${monthyear} ${dateday}`,
          dayNumber: dayNumber,
          dayOfWeek: dayOfWeek,
          isToday,
          prayers
        };
      });
    });
    
    log(`Extracted data for ${extractedData.length} days`);
    
    // Save raw data for debugging
    fs.writeFileSync(
      path.join(outputDir, 'raw_data.json'),
      JSON.stringify(extractedData, null, 2)
    );
    
    if (extractedData.length === 0) {
      throw new Error('No prayer data found on the page');
    }
    
    // Process the data into athan and iqama formats with day number and day of week
    log('Processing extracted week data...');
    const processedWeekData = [];
    
    extractedData.forEach(day => {
      // Skip any entries with invalid day numbers
      if (day.dayNumber <= 0) {
        log(`Skipping entry with invalid day number: ${day.date}`, 'warn');
        return;
      }
      
      const athanRow = { Fajr: '', Sunrise: '', Dhuhr: '', Asr: '', Maghrib: '', Isha: '' };
      const iqamaRow = { Fajr: '', Dhuhr: '', Asr: '', Maghrib: '', Isha: '' };
      
      // Process each prayer
      Object.entries(day.prayers).forEach(([name, times]) => {
        // Fix the "Magrib" to "Maghrib" spelling
        const correctedName = name === 'Magrib' ? 'Maghrib' : name;
        
        // Convert times to 24-hour format
        const start24 = convertTo24Hour(times.start, name);
        const iqamah24 = convertTo24Hour(times.iqamah, name);
        
        // Add to athan row
        if (athanRow.hasOwnProperty(correctedName)) {
          athanRow[correctedName] = start24;
        }
        
        // Add to iqama row (all prayers except Sunrise)
        if (iqamaRow.hasOwnProperty(correctedName) && correctedName !== 'Sunrise') {
          iqamaRow[correctedName] = iqamah24;
        }
      });
      
      processedWeekData.push({
        dayNumber: day.dayNumber,
        dayOfWeek: day.dayOfWeek,
        isToday: day.isToday,
        athan: athanRow,
        iqama: iqamaRow
      });
    });
    
    // Log processed data
    log(`Processed ${processedWeekData.length} days of data`);
    log(`Sample athan data: ${JSON.stringify(processedWeekData[0].athan)}`);
    
    // Sort by day number to ensure proper order
    processedWeekData.sort((a, b) => a.dayNumber - b.dayNumber);
    
    // Create full month data
    const today = new Date();
    const currentMonth = today.getMonth();
    const currentYear = today.getFullYear();
    const daysInMonth = new Date(currentYear, currentMonth + 1, 0).getDate();
    
    log(`Creating full month data for ${daysInMonth} days`);
    
    // Create mapping of day of week to prayer times
    const dayOfWeekMap = {};
    processedWeekData.forEach(day => {
      if (day.dayOfWeek >= 0) {
        dayOfWeekMap[day.dayOfWeek] = {
          athan: day.athan,
          iqama: day.iqama
        };
      }
    });
    
    // Generate the full month data
    const athanMonth = [];
    const iqamaMonth = [];
    
    for (let day = 1; day <= daysInMonth; day++) {
      // Check if we have real data for this day
      const dayData = processedWeekData.find(d => d.dayNumber === day);
      
      if (dayData) {
        // We have actual data for this day
        log(`Using actual data for day ${day}`);
        athanMonth.push({
          day: day,
          ...dayData.athan
        });
        
        iqamaMonth.push({
          day: day,
          ...dayData.iqama
        });
      } else {
        // No actual data, use day of week pattern
        const date = new Date(currentYear, currentMonth, day);
        const dayOfWeek = date.getDay(); // 0-6
        
        if (dayOfWeekMap[dayOfWeek]) {
          // We have a matching day of week pattern
          log(`Using day of week ${dayOfWeek} pattern for day ${day}`);
          athanMonth.push({
            day: day,
            ...dayOfWeekMap[dayOfWeek].athan
          });
          
          iqamaMonth.push({
            day: day,
            ...dayOfWeekMap[dayOfWeek].iqama
          });
        } else {
          // Fallback: use data from first day
          log(`No matching day of week pattern for day ${day}, using fallback`, 'warn');
          athanMonth.push({
            day: day,
            ...processedWeekData[0].athan
          });
          
          iqamaMonth.push({
            day: day,
            ...processedWeekData[0].iqama
          });
        }
      }
    }
    
    // Helper function to generate CSV files for a specific month
    async function generateMonthCSVs(targetMonth, targetYear, monthData, monthName) {
      // Create headers for the CSV files
      const athanHeaders = [
        { id: 'day', title: 'Day' },
        { id: 'Fajr', title: 'Fajr' },
        { id: 'Sunrise', title: 'Sunrise' },
        { id: 'Dhuhr', title: 'Dhuhr' },
        { id: 'Asr', title: 'Asr' },
        { id: 'Maghrib', title: 'Maghrib' },
        { id: 'Isha', title: 'Isha' }
      ];
      
      const iqamaHeaders = [
        { id: 'day', title: 'Day' },
        { id: 'Fajr', title: 'Fajr' },
        { id: 'Dhuhr', title: 'Dhuhr' },
        { id: 'Asr', title: 'Asr' },
        { id: 'Maghrib', title: 'Maghrib' },
        { id: 'Isha', title: 'Isha' }
      ];
      
      // Create the CSV writers with month name in filename
      const athanCsvWriter = createCsvWriter({
        path: path.join(outputDir, `athan_times_${monthName}.csv`),
        header: athanHeaders
      });
      
      const iqamaCsvWriter = createCsvWriter({
        path: path.join(outputDir, `iqama_times_${monthName}.csv`),
        header: iqamaHeaders
      });
      
      // Write the CSV files
      await athanCsvWriter.writeRecords(monthData.athan);
      log(`✅ Athan times for ${monthName} saved to ${path.join(outputDir, `athan_times_${monthName}.csv`)}`);
      
      await iqamaCsvWriter.writeRecords(monthData.iqama);
      log(`✅ Iqama times for ${monthName} saved to ${path.join(outputDir, `iqama_times_${monthName}.csv`)}`);
    }
    
    // Get current month name
    const monthName = today.toLocaleString('default', { month: 'long' });
    
    // Generate CSV files for current month
    log(`📅 Generating CSV files for current month: ${monthName}`);
    await generateMonthCSVs(currentMonth, currentYear, {
      athan: athanMonth,
      iqama: iqamaMonth
    }, monthName);
    
    // Generate CSV files for next month as well
    const nextMonthDate = new Date(currentYear, currentMonth + 1, 1);
    const nextMonth = nextMonthDate.getMonth();
    const nextYear = nextMonthDate.getFullYear();
    const nextMonthName = nextMonthDate.toLocaleString('default', { month: 'long' });
    const daysInNextMonth = new Date(nextYear, nextMonth + 1, 0).getDate();
    
    log(`📅 Generating CSV files for next month: ${nextMonthName}`);
    
    // Generate data for next month using the day-of-week pattern
    const athanNextMonth = [];
    const iqamaNextMonth = [];
    
    for (let day = 1; day <= daysInNextMonth; day++) {
      const date = new Date(nextYear, nextMonth, day);
      const dayOfWeek = date.getDay(); // 0-6
      
      if (dayOfWeekMap[dayOfWeek]) {
        // Use day of week pattern
        athanNextMonth.push({
          day: day,
          ...dayOfWeekMap[dayOfWeek].athan
        });
        
        iqamaNextMonth.push({
          day: day,
          ...dayOfWeekMap[dayOfWeek].iqama
        });
      } else {
        // Fallback to first day's data
        athanNextMonth.push({
          day: day,
          ...processedWeekData[0].athan
        });
        
        iqamaNextMonth.push({
          day: day,
          ...processedWeekData[0].iqama
        });
      }
    }
    
    await generateMonthCSVs(nextMonth, nextYear, {
      athan: athanNextMonth,
      iqama: iqamaNextMonth
    }, nextMonthName);
    
    log('✅ Prayer times extraction completed successfully for current and next month!');
    
    return { athanMonth, iqamaMonth };
  } catch (error) {
    logError('Error during extraction', error);
    throw error;
  } finally {
    if (browser) {
      await browser.close();
      log('Browser closed');
    }
  }
}

// Run the extraction
extractPrayerTimes()
  .then(() => {
    log('Script completed successfully!');
    process.exit(0);
  })
  .catch(error => {
    log(`Script failed: ${error.message}`, 'error');
    process.exit(1);
  });