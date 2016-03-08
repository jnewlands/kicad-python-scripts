#
# KiCad python module for interpreting generic netlists which can be used
# to generate Bills of materials, etc.
#
# No string formatting is used on purpose as the only string formatting that
# is current compatible with python 2.4+ to 3.0+ is the '%' method, and that
# is due to be deprecated in 3.0+ soon
#

"""
    @package
    Generate a HTML BOM list.
    Components are sorted and grouped by value
    Fields are (if exist)
    Ref, Quantity, Value, Part, Datasheet, Description, Vendor
"""


from __future__ import print_function
import sys
import xml.sax as sax
import re
import pdb

from bomfunk_csv import CSV_DEFAULT as CSV_DEFAULT
from bomfunk_csv import CSV_PROTECTED as CSV_PROTECTED
from bomfunk_csv import CSV_MATCH as CSV_MATCH

import bomfunk_units

#'better' sorting function which sorts by NUMERICAL value not ASCII
def natural_sort(string):
	return [int(s) if s.isdigit() else s for s in re.split(r'(\d+)',string)]

#-----<Configure>----------------------------------------------------------------

# excluded_fields is a list of regular expressions.  If any one matches a field
# from either a component or a libpart, then that will not be included as a
# column in the BOM.  Otherwise all columns from all used libparts and components
# will be unionized and will appear.  Some fields are impossible to blacklist, such
# as Ref, Value, Footprint, and Datasheet.  Additionally Qty and Item are supplied
# unconditionally as columns, and may not be removed.
excluded_fields = [
    #'Price@1000'
    ]


# You may exlude components from the BOM by either:
#
# 1) adding a custom field named "Installed" to your components and filling it
# with a value of "NU" (Normally Uninstalled).
# See netlist.getInterestingComponents(), or
#
# 2) blacklisting it in any of the three following lists:


# regular expressions which match component 'Reference' fields of components that
# are to be excluded from the BOM.
excluded_references = [
    'TP[0-9]+'              # all test points
    ]


# regular expressions which match component 'Value' fields of components that
# are to be excluded from the BOM.
excluded_values = [
    'MOUNTHOLE',
    'SCOPETEST',
    'MOUNT_HOLE',
    'SOLDER_BRIDGE.*'
    ]


# regular expressions which match component 'Footprint' fields of components that
# are to be excluded from the BOM.
excluded_footprints = [
    #'MOUNTHOLE'
    ]

# When comparing part names, components will match if they are both elements of the
# same set defined here
ALIASES = [
    ["c", "c_small", "cap", "capacitor"],
    ["r", "r_small", "res", "resistor"],
    ["sw", "switch"]
    ]

DNF = ["dnf", "do not fit", "nofit", "no stuff", "nostuff", "noload", "do not load"]

#-----</Configure>---------------------------------------------------------------



class xmlElement():
    """xml element which can represent all nodes of the netlist tree.  It can be
    used to easily generate various output formats by propogating format
    requests to children recursively.
    """
    def __init__(self, name, parent=None):
        self.name = name
        self.attributes = {}
        self.parent = parent
        self.chars = ""
        self.children = []

    def __str__(self):
        """String representation of this netlist element

        """
        return self.name + "[" + self.chars + "]" + " attr_count:" + str(len(self.attributes))

    def formatXML(self, nestLevel=0, amChild=False):
        """Return this element formatted as XML

        Keywords:
        nestLevel -- increases by one for each level of nesting.
        amChild -- If set to True, the start of document is not returned.

        """
        s = ""

        indent = ""
        for i in range(nestLevel):
            indent += "    "

        if not amChild:
            s = "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"

        s += indent + "<" + self.name
        for a in self.attributes:
            s += " " + a + "=\"" + self.attributes[a] + "\""

        if (len(self.chars) == 0) and (len(self.children) == 0):
            s += "/>"
        else:
            s += ">" + self.chars

        for c in self.children:
            s += "\n"
            s += c.formatXML(nestLevel+1, True)

        if (len(self.children) > 0):
            s += "\n" + indent

        if (len(self.children) > 0) or (len(self.chars) > 0):
            s += "</" + self.name + ">"

        return s

    def formatHTML(self, amChild=False):
        """Return this element formatted as HTML

        Keywords:
        amChild -- If set to True, the start of document is not returned

        """
        s = ""

        if not amChild:
            s = """<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"
                "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
                <html xmlns="http://www.w3.org/1999/xhtml">
                <head>
                <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
                <title></title>
                </head>
                <body>
                <table>
                """

        s += "<tr><td><b>" + self.name + "</b><br>" + self.chars + "</td><td><ul>"
        for a in self.attributes:
            s += "<li>" + a + " = " + self.attributes[a] + "</li>"

        s += "</ul></td></tr>\n"

        for c in self.children:
            s += c.formatHTML(True)

        if not amChild:
            s += """</table>
                </body>
                </html>"""

        return s

    def addAttribute(self, attr, value):
        """Add an attribute to this element"""
        self.attributes[attr] = value

    def setAttribute(self, attr, value):
        """Set an attributes value - in fact does the same thing as add
        attribute

        """
        self.attributes[attr] = value

    def setChars(self, chars):
        """Set the characters for this element"""
        self.chars = chars

    def addChars(self, chars):
        """Add characters (textual value) to this element"""
        self.chars += chars

    def addChild(self, child):
        """Add a child element to this element"""
        self.children.append(child)
        return self.children[len(self.children) - 1]

    def getParent(self):
        """Get the parent of this element (Could be None)"""
        return self.parent

    def getChild(self, name):
        """Returns the first child element named 'name'

        Keywords:
        name -- The name of the child element to return"""
        for child in self.children:
            if child.name == name:
                return child
        return None

    def getChildren(self, name=None):
        if name:
            # return _all_ children named "name"
            ret = []
            for child in self.children:
                if child.name == name:
                    ret.append(child)
            return ret
        else:
            return self.children

    def get(self, elemName, attribute="", attrmatch=""):
        """Return the text data for either an attribute or an xmlElement
        """
        if (self.name == elemName):
            if attribute != "":
                try:
                    if attrmatch != "":
                        if self.attributes[attribute] == attrmatch:
                            return self.chars
                    else:
                        return self.attributes[attribute]
                except AttributeError:
                    return ""
            else:
                return self.chars

        for child in self.children:
            ret = child.get(elemName, attribute, attrmatch)
            if ret != "":
                return ret

        return ""



class libpart():
    """Class for a library part, aka 'libpart' in the xml netlist file.
    (Components in eeschema are instantiated from library parts.)
    This part class is implemented by wrapping an xmlElement with accessors.
    This xmlElement instance is held in field 'element'.
    """
    def __init__(self, xml_element):
        #
        self.element = xml_element

    #def __str__(self):
        # simply print the xmlElement associated with this part
        #return str(self.element)

    def getLibName(self):
        return self.element.get("libpart", "lib")

    def getPartName(self):
        return self.element.get("libpart", "part")

    def getDescription(self):
        return self.element.get("description")

    def getDocs(self):
        return self.element.get("docs")

    def getField(self, name):
        return self.element.get("field", "name", name)

    def getFieldNames(self):
        """Return a list of field names in play for this libpart.
        """
        fieldNames = []
        fields = self.element.getChild('fields')
        if fields:
            for f in fields.getChildren():
                fieldNames.append( f.get('field','name') )
        return fieldNames

    def getDatasheet(self):

        datasheet = self.getField("Datasheet")

        if not datasheet or datasheet == "":
            docs = self.getDocs()

            if "http" in docs or ".pdf" in docs:
                datasheet = docs

        return datasheet

    def getFootprint(self):
        return self.getField("Footprint")

    def getAliases(self):
        """Return a list of aliases or None"""
        aliases = self.element.getChild("aliases")
        if aliases:
            ret = []
            children = aliases.getChildren()
            # grab the text out of each child:
            for child in children:
                ret.append( child.get("alias") )
            return ret
        return None


class comp():
    """Class for a component, aka 'comp' in the xml netlist file.
    This component class is implemented by wrapping an xmlElement instance
    with accessors.  The xmlElement is held in field 'element'.
    """

    def __init__(self, xml_element):
        self.element = xml_element
        self.libpart = None

        # Set to true when this component is included in a component group
        self.grouped = False

    #compare the value of this part, to the value of another part (see if they match)
    def compareValue(self, other):
        #simple string comparison
        if self.getValue().lower() == other.getValue().lower(): return True

        #otherwise, perform a more complicate value comparison
        if bomfunk_units.compareValues(self.getValue(), other.getValue()): return True

        #no match, return False
        return False

    #compare footprint with another component
    def compareFootprint(self, other):
        return self.getFootprint().lower() == other.getFootprint().lower()

    #compare the component library of this part to another part
    def compareLibName(self, other):
        return self.getLibName().lower() == other.getLibName().lower()

    def compareRating(self, other):
        myRating = self.getField("Rating")
        theirRating = other.getField("Rating")

        #TODO
        pass

    #determine if two parts have the same name
    def comparePartName(self, other):
        pn1 = self.getPartName().lower()
        pn2 = other.getPartName().lower()

        #simple direct match
        if pn1 == pn2: return True

        #compare part aliases e.g. "c" to "c_small"
        for alias in ALIASES:
            if pn1 in alias and pn2 in alias:
                return True

        return False

    def __eq__(self, other):
        """Equlivalency operator, remember this can be easily overloaded"""

        #special case for connectors, as the "Value" is the description of the connector (and is somewhat meaningless)
        if "connector" in self.getDescription().lower():
            #ignore "value"
            valueResult = True
        else:
            valueResult = self.compareValue(other)

        return valueResult and self.compareFootprint(other) and self.compareLibName(other) and self.comparePartName(other) and self.isFitted() == other.isFitted()

    def setLibPart(self, part):
        self.libpart = part

    def getPrefix(self): #return the reference prefix
        #e.g. if this component has a reference U12, will return "U"
        prefix = ""

        for c in self.getRef():
            if c.isalpha(): prefix += c
            else: break

        return prefix

    def getLibPart(self):
        return self.libpart

    def getPartName(self):
        return self.element.get("libsource", "part")

    def getLibName(self):
        return self.element.get("libsource", "lib")

    def setValue(self, value):
        """Set the value of this component"""
        v = self.element.getChild("value")
        if v:
            v.setChars(value)

    def getValue(self):
        return self.element.get("value")

    def getField(self, name, libraryToo=True):
        """Return the value of a field named name. The component is first
        checked for the field, and then the components library part is checked
        for the field. If the field doesn't exist in either, an empty string is
        returned

        Keywords:
        name -- The name of the field to return the value for
        libraryToo --   look in the libpart's fields for the same name if not found
                        in component itself
        """

        field = self.element.get("field", "name", name)
        if field == "" and libraryToo:
            field = self.libpart.getField(name)
        return field

    def getFieldNames(self):
        """Return a list of field names in play for this component.  Mandatory
        fields are not included, and they are: Value, Footprint, Datasheet, Ref.
        The netlist format only includes fields with non-empty values.  So if a field
        is empty, it will not be present in the returned list.
        """
        fieldNames = []
        fields = self.element.getChild('fields')
        if fields:
            for f in fields.getChildren():
                fieldNames.append( f.get('field','name') )
        return fieldNames

    def getRef(self):
        return self.element.get("comp", "ref")

    #determine if a component is FITTED or not
    def isFitted(self):

        check = [self.getValue().lower(), self.getField("Notes").lower()]

        for item in check:
            if any([dnf in item for dnf in DNF]): return False

        return True

    def getFootprint(self, libraryToo=True):
        ret = self.element.get("footprint")
        if ret =="" and libraryToo:
            ret = self.libpart.getFootprint()
        return ret

    def getDatasheet(self, libraryToo=True):
        return self.libpart.getDatasheet()

    def getTimestamp(self):
        return self.element.get("tstamp")

    def getDescription(self):
        return self.libpart.getDescription()

class ComponentGroup():

    def __init__(self):
        self.components = []
        self.fields = dict.fromkeys(CSV_DEFAULT)    #columns loaded from KiCAD
        self.csvFields = dict.fromkeys(CSV_DEFAULT) #columns loaded from .csv file
        
    def getField(self, field):
        if not field in self.fields.keys(): return ""
        if not self.fields[field]: return ""
        return str(self.fields[field])
        
    def getCSVField(self, field):
    
        #ignore protected fields
        if field in CSV_PROTECTED: return ""
    
        if not field in self.csvFields.keys(): return ""
        if not self.csvFields[field]: return ""
        return str(self.csvFields[field])

    def getHarmonizedField(self,field):

        #for protected fields, source from KiCAD
        if field in CSV_PROTECTED:
            return self.getField(field)

        #if there is kicad data, that takes preference
        if not self.getField(field) == "":
            return self.getField(field)

        elif not self.getCSVField(field) == "":
            return self.getCSVField(field)
        else:
            return ""
        
        
    def compareCSVLine(self, line):
        """
        Compare a line (dict) and see if it matches this component group
        """
        for field in CSV_MATCH:
            if not field in line.keys(): return False
            if not field in self.fields.keys(): return False
            if not line[field] == self.fields[field]: return False
            
        return True
        
    def getCount(self):
        for c in self.components:
            if not c.isFitted(): return "0"
        return len(self.components)

    #Test if a given component fits in this group
    def matchComponent(self, c):
        if len(self.components) == 0: return True
        if c == self.components[0]: return True

    #test if a given component is already contained in this grop
    def containsComponent(self, c):
        if self.matchComponent(c) == False: return False
        
        for comp in self.components:
            if comp.getRef() == c.getRef(): return True
            
        return False

    #add a component to the group
    def addComponent(self, c):
    
        if len(self.components) == 0:
            self.components.append(c)
        elif self.containsComponent(c):
            return
        elif self.matchComponent(c):
            self.components.append(c)

    def isFitted(self):
        return any([c.isFitted() for c in self.components])

    #return a list of the components
    def getRefs(self):
        #print([c.getRef() for c in self.components]))
        #return " ".join([c.getRef() for c in self.components]) 
        return " ".join([c.getRef() for c in self.components])

    #sort the components in correct order
    def sortComponents(self):
        self.components = sorted(self.components, key=lambda c: natural_sort(c.getRef()))   
        
    #update a given field, based on some rules and such
    def updateField(self, field, fieldData):
        
        if field in CSV_PROTECTED: return

        if (field == None or field == ""): return
        elif fieldData == "" or fieldData == None:
            return
        elif (not field in self.fields.keys()) or (self.fields[field] == None) or (self.fields[field] == ""):
            self.fields[field] = fieldData
        elif fieldData.lower() in self.fields[field].lower():
            return
        else:
            print("Conflict:",self.fields[field],",",fieldData)
            self.fields[field] += " " + fieldData
        
    def updateFields(self):
    
        for f in CSV_DEFAULT:
            
            #get info from each field
            for c in self.components:
                
                self.updateField(f, c.getField(f))
                     
        #update 'global' fields
        self.fields["References"] = self.getRefs()

        self.fields["Quantity"] = self.getCount()

        self.fields["Value"] = self.components[0].getValue()

        self.fields["Part"] = self.components[0].getPartName()

        self.fields["Description"] = self.components[0].getDescription()

        self.fields["Datasheet"] = self.components[0].getDatasheet()

        self.fields["Footprint"] = self.components[0].getFootprint().split(":")[-1]

    #return a dict of the CSV data based on the supplied columns
    def getCSVRow(self, columns):
        row = [self.getCSVField(key) for key in columns]
        return row

    #return a dict of the KiCAD data based on the supplied columns
    def getKicadRow(self, columns):
        row = [self.getField(key) for key in columns]
        #print(row)
        return row

    #return a dict of harmonized data based on the supplied columns
    def getHarmonizedRow(self,columns):
        return [self.getHarmonizedField(key) for key in columns]

class netlist():
    """ Kicad generic netlist class. Generally loaded from a kicad generic
    netlist file. Includes several helper functions to ease BOM creating
    scripts

    """
    def __init__(self, fname=""):
        """Initialiser for the genericNetlist class

        Keywords:
        fname -- The name of the generic netlist file to open (Optional)

        """
        self.design = None
        self.components = []
        self.libparts = []
        self.libraries = []
        self.nets = []

        # The entire tree is loaded into self.tree
        self.tree = []

        self._curr_element = None

        # component blacklist regexs, made from exluded_* above.
        self.excluded_references = []
        self.excluded_values = []
        self.excluded_footprints = []

        if fname != "":
            self.load(fname)

    def addChars(self, content):
        """Add characters to the current element"""
        self._curr_element.addChars(content)

    def addElement(self, name):
        """Add a new kicad generic element to the list"""
        if self._curr_element == None:
            self.tree = xmlElement(name)
            self._curr_element = self.tree
        else:
            self._curr_element = self._curr_element.addChild(
                xmlElement(name, self._curr_element))

        # If this element is a component, add it to the components list
        if self._curr_element.name == "comp":
            self.components.append(comp(self._curr_element))

        # Assign the design element
        if self._curr_element.name == "design":
            self.design = self._curr_element

        # If this element is a library part, add it to the parts list
        if self._curr_element.name == "libpart":
            self.libparts.append(libpart(self._curr_element))

        # If this element is a net, add it to the nets list
        if self._curr_element.name == "net":
            self.nets.append(self._curr_element)

        # If this element is a library, add it to the libraries list
        if self._curr_element.name == "library":
            self.libraries.append(self._curr_element)

        return self._curr_element

    def endDocument(self):
        """Called when the netlist document has been fully parsed"""
        # When the document is complete, the library parts must be linked to
        # the components as they are seperate in the tree so as not to
        # duplicate library part information for every component
        for c in self.components:
            for p in self.libparts:
                if p.getLibName() == c.getLibName():
                    if p.getPartName() == c.getPartName():
                        c.setLibPart(p)
                        break
                    else:
                        aliases = p.getAliases()
                        if aliases and self.aliasMatch( c.getPartName(), aliases ):
                            c.setLibPart(p)
                            break;

            if not c.getLibPart():
                print( 'missing libpart for ref:', c.getRef(), c.getPartName(), c.getLibName() )


    def aliasMatch(self, partName, aliasList):
        for alias in aliasList:
            if partName == alias:
                return True
        return False

    def endElement(self):
        """End the current element and switch to its parent"""
        self._curr_element = self._curr_element.getParent()

    def getDate(self):
        """Return the date + time string generated by the tree creation tool"""
        return self.design.get("date")

    def getSource(self):
        """Return the source string for the design"""
        return self.design.get("source")

    def getTool(self):
        """Return the tool string which was used to create the netlist tree"""
        return self.design.get("tool")
        
    def getSheet(self):
        return self.design.getChild("sheet")
        
    def getVersion(self):
        """Return the verison of the sheet info"""
        sheet = self.getSheet()
        if sheet == None: return ""
        return sheet.get("rev")

    def gatherComponentFieldUnion(self, components=None):
        """Gather the complete 'set' of unique component fields, fields found in any component.
        """
        if not components:
            components=self.components

        s = set()
        for c in components:
            s.update( c.getFieldNames() )

        # omit anything matching any regex in excluded_fields
        ret = set()
        for field in s:
            exclude = False
            for rex in excluded_fields:
                if re.match( rex, field ):
                    exclude = True
                    break
            if not exclude:
                ret.add(field)

        return ret       # this is a python 'set'

    def gatherLibPartFieldUnion(self):
        """Gather the complete 'set' of part fields, fields found in any part.
        """
        s = set()
        for p in self.libparts:
            s.update( p.getFieldNames() )

        # omit anything matching any regex in excluded_fields
        ret = set()
        for field in s:
            exclude = False
            for rex in excluded_fields:
                if re.match( rex, field ):
                    exclude = True
                    break
            if not exclude:
                ret.add(field)

        return ret       # this is a python 'set'

    def getInterestingComponents(self):
        """Return a subset of all components, those that should show up in the BOM.
        Omit those that should not, by consulting the blacklists:
        excluded_values, excluded_refs, and excluded_footprints, which hold one
        or more regular expressions.  If any of the the regular expressions match
        the corresponding field's value in a component, then the component is exluded.
        """

        # pre-compile all the regex expressions:
        del self.excluded_references[:]
        del self.excluded_values[:]
        del self.excluded_footprints[:]

        for rex in excluded_references:
            self.excluded_references.append( re.compile( rex ) )

        for rex in excluded_values:
            self.excluded_values.append( re.compile( rex ) )

        for rex in excluded_footprints:
            self.excluded_footprints.append( re.compile( rex ) )

        # the subset of components to return, considered as "interesting".
        ret = []

        # run each component thru a series of tests, if it passes all, then add it
        # to the interesting list 'ret'.
        for c in self.components:
            exclude = False
            if not exclude:
                for refs in self.excluded_references:
                    if refs.match(c.getRef()):
                        exclude = True
                        break;
            if not exclude:
                for vals in self.excluded_values:
                    if vals.match(c.getValue()):
                        exclude = True
                        break;
            if not exclude:
                for mods in self.excluded_footprints:
                    if mods.match(c.getFootprint()):
                        exclude = True
                        break;

            if not exclude:
                # This is a fairly personal way to flag DNS (Do Not Stuff).  NU for
                # me means Normally Uninstalled.  You can 'or in' another expression here.
                if c.getField( "Installed" ) == 'NU':
                    exclude = True

            if not exclude:
                ret.append(c)

        # Sort first by ref as this makes for easier to read BOM's
        ret.sort(key=lambda g: g.getRef())

        return ret


    def groupComponents(self, components = None):
        """Return a list of component lists. Components are grouped together
        when the value, library and part identifiers match.
		
		ALSO THE FOOTPRINTS MUST MATCH YOU DINGBAT

        Keywords:
        components -- is a list of components, typically an interesting subset
        of all components, or None.  If None, then all components are looked at.
        """
        if not components:
            components = self.components

        groups = []
        
        for c in components:
            found = False
            
            for g in groups:
                if g.matchComponent(c):
                    g.addComponent(c)
                    found = True
                    break
            
            if not found:
                g = ComponentGroup()
                g.addComponent(c)
                groups.append(g)
            
        #sort the references within each group
        for g in groups:
            g.sortComponents()
            g.updateFields()

        #sort the groups
        #first priority is the Type of component (e.g. R, U,
        groups = sorted(groups, key=lambda g: [g.components[0].getPrefix(), g.components[0].getValue()])
        #sort the groups by the first part in the group
#        groups = sorted(groups, key = lambda g: natural_sort(g.components[0].getRef()))
                
        return groups

    def getGroupField(self, group, field):
        """Return the whatever is known about the given field by consulting each
        component in the group.  If any of them know something about the property/field,
        then return that first non-blank value.
        """
        for c in group:
            ret = c.getField(field, False)
            if ret != '':
                return ret
        return group[0].getLibPart().getField(field)

    def getGroupFootprint(self, group):
        """Return the whatever is known about the Footprint by consulting each
        component in the group.  If any of them know something about the Footprint,
        then return that first non-blank value.
        """
        for c in group:
            ret = c.getFootprint()
            if ret != "":
                return ret
        return group[0].getLibPart().getFootprint()

    def getGroupDatasheet(self, group):
        """Return the whatever is known about the Datasheet by consulting each
        component in the group.  If any of them know something about the Datasheet,
        then return that first non-blank value.
        """
        for c in group:
            ret = c.getDatasheet()
            if ret != "":
                return ret

        if len(group) > 0:
            return group[0].getLibPart().getDatasheet()
        else:
            print("NULL!")
        return ''

    def formatXML(self):
        """Return the whole netlist formatted in XML"""
        return self.tree.formatXML()

    def formatHTML(self):
        """Return the whole netlist formatted in HTML"""
        return self.tree.formatHTML()

    def load(self, fname):
        """Load a kicad generic netlist

        Keywords:
        fname -- The name of the generic netlist file to open

        """
        try:
            self._reader = sax.make_parser()
            self._reader.setContentHandler(_gNetReader(self))
            self._reader.parse(fname)
        except IOError as e:
            print( __file__, ":", e, file=sys.stderr )
            sys.exit(-1)



class _gNetReader(sax.handler.ContentHandler):
    """SAX kicad generic netlist content handler - passes most of the work back
    to the 'netlist' class which builds a complete tree in RAM for the design

    """
    def __init__(self, aParent):
        self.parent = aParent

    def startElement(self, name, attrs):
        """Start of a new XML element event"""
        element = self.parent.addElement(name)

        for name in attrs.getNames():
            element.addAttribute(name, attrs.getValue(name))

    def endElement(self, name):
        self.parent.endElement()

    def characters(self, content):
        # Ignore erroneous white space - ignoreableWhitespace does not get rid
        # of the need for this!
        if not content.isspace():
            self.parent.addChars(content)

    def endDocument(self):
        """End of the XML document event"""
        self.parent.endDocument()
