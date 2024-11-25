# To debug this within lldb, insert the following code wherever you need to break:
#
#   import pdb
#   pdb.set_trace()

DEBUG = 0

import lldb
if DEBUG:
  import debugpy

def String( valobj: lldb.SBValue, internal_dict, options ):
  data: lldb.SBValue = valobj.GetChildMemberWithName('data')
  len = valobj.GetChildMemberWithName('count').GetValueAsSigned(0)
  if len == 0:
    return ""
  if len < 0:
    return "invalid length (" + str(len) + ")"
  if len > 0xFFFFFFFF:
    return "length is too big for LLDB's puny python bridge (" + str(len) + ")"
  # HACK: Assume it's utf-8.... I wonder if options contains an encoding option?
  return ( '"'
           + bytes( data.GetPointeeData(0, len).uint8s ).decode( 'utf-8' )
           + '"' )
   
# Annoyingly summary strings suppress the printing of the child members by
# default. This is crappy, and means we have to write that code ourselves, but
# it's not even that trivial as just printing the "GetValue()" of each child
# prints "None", helpfully.

def Array_View( valobj: lldb.SBValue, internal_dict, options ):
  raw: lldb.SBValue = valobj.GetNonSyntheticValue()
  return ( "Array_View64(count="
           + str( raw.GetChildMemberWithName( 'count' ).GetValueAsSigned() )
           + ")" )

def ResizableArray( valobj: lldb.SBValue, internal_dict, options ):
  raw: lldb.SBValue = valobj.GetNonSyntheticValue()
  count = raw.GetChildMemberWithName( 'count' )
  name = 'count'
  if count.error.Fail(): # Braid’s arrays have the same type name but different members
    count = raw.GetChildMemberWithName( 'items' )
    name = 'items'
  allocated = raw.GetChildMemberWithName( 'allocated_' + name )
  return ( "Array(" + name + "="
           + str( count.GetValueAsSigned() )
           + ",allocated_" + name + "="
           + str( allocated.GetValueAsSigned() )
           + ")" )

def ResizableLocalArray( valobj: lldb.SBValue, internal_dict, options ):
  raw: lldb.SBValue = valobj.GetNonSyntheticValue()
  return ( "Local_Array(count="
           + str( raw.GetChildMemberWithName( 'count' ).GetValueAsSigned() )
           + ",allocated_count="
           + str( raw.GetChildMemberWithName( 'allocated_count' ).GetValueAsSigned() )
           + ")" )

def BucketArray( valobj: lldb.SBValue, internal_dict, options ):
  raw: lldb.SBValue = valobj.GetNonSyntheticValue()
  return ( "Bucket_Array(count="
           + str( raw.GetChildMemberWithName( 'count' ).GetValueAsSigned() )
           + ")" )

class ArrayChildrenProvider:
  def __init__( self, valobj: lldb.SBValue, internal_dict):
    self.val = valobj
    self.native = ["count", "data"]

  def update(self):
    count = self.val.GetChildMemberWithName( 'count' )
    if count.error.Fail(): # Braid’s arrays have the same type name but different members
      count = self.val.GetChildMemberWithName( 'items' )
    self.count = count.GetValueAsSigned()
    self.data: lldb.SBValue = self.val.GetChildMemberWithName('data')
    self.data_type: lldb.SBType = self.data.GetType().GetPointeeType()
    self.data_size = self.data_type.GetByteSize()

    return False

  def has_children(self):
    return True

  def num_children(self):
    return len(self.native) + self.count;

  def get_child_index(self, name):
    try:
      return self.native.index(name)
    except ValueError:
      return len(self.native) + int( name )

  def get_child_at_index(self, child_index):
    if child_index < len(self.native):
      return self.val.GetChildMemberWithName(self.native[child_index])
      
    index = child_index - len(self.native);
    return self.data.CreateChildAtOffset( '[' + str(index) + ']',
                                          self.data_size * index,
                                          self.data_type )


class ResizableArrayChildrenProvider(ArrayChildrenProvider):
  def __init__( self, valobj: lldb.SBValue, internal_dict):
    ArrayChildrenProvider.__init__(self, valobj, internal_dict)
    count = self.val.GetChildMemberWithName( 'count' )
    if count.error.Fail(): # Braid’s arrays have the same type name but different members
        self.native = ["items", "allocated_items", "data"]
    else:
        self.native = ["count", "allocated_count", "data"]

class ResizableLocalArrayChildrenProvider(ArrayChildrenProvider):
  def __init__( self, valobj: lldb.SBValue, internal_dict):
    ArrayChildrenProvider.__init__(self, valobj, internal_dict)
    self.native = ["count", "allocated_count", "data", "local_storage"]


class BucketArrayChildrenProvider:
  def __init__( self, valobj: lldb.SBValue, internal_dict) :
    self.val = valobj
    self.native = ["count", "first_bucket", "current_bucket"]

  def update(self):
    self.count = self.val.GetChildMemberWithName( 'count' ).GetValueAsSigned()
    self.first_bucket = self.val.GetChildMemberWithName('first_bucket');
    self.data_type: lldb.SBType = self.first_bucket.GetChildMemberWithName('data').GetType().GetArrayElementType();
    self.data_size = self.data_type.GetByteSize()
    # self.data: lldb.SBValue = self.val.GetChildMemberWithName('data')
    # self.data_type: lldb.SBType = self.data.GetType().GetPointeeType()
    # self.data_size = self.data_type.GetByteSize()

    return False

  def has_children(self):
    return True

  def num_children(self):
    return len(self.native) + self.count;

  def get_child_index(self, name):
    try:
      return self.native.index(name)
    except ValueError:
      return len(self.native) + int( name )

  def get_child_at_index(self, child_index):
    if child_index < len(self.native):
      return self.val.GetChildMemberWithName(self.native[child_index])
      
    index = child_index - len(self.native);
    bucket = self.first_bucket;
    i = index;
    while i >= bucket.GetChildMemberWithName('count').GetValueAsSigned():
        i -= bucket.GetChildMemberWithName('count').GetValueAsSigned()
        bucket = bucket.GetChildMemberWithName('next')

    return bucket.GetChildMemberWithName('data').CreateChildAtOffset( '[' + str(index) + ']',
                                          self.data_size * i,
                                          self.data_type )


def __lldb_init_module( debugger: lldb.SBDebugger, dict ):
  if DEBUG:
    debugpy.listen( 5432 )
    debugpy.wait_for_client()

  C = debugger.HandleCommand
  C(  "type summary add    -w JaiCompiler Newstring -F jaicompilertype.String" )
  C(  "type summary add -e -w JaiCompiler Array_View64 -F jaicompilertype.Array_View" )
  C( r"type summary add -e -w JaiCompiler -x '^Array<.*>$' -F jaicompilertype.ResizableArray" )
  C( r"type summary add -e -w JaiCompiler -x '^Local_Array<.*>$' -F jaicompilertype.ResizableLocalArray" )
  C( r"type summary add -e -w JaiCompiler -x '^Bucket_Array<.*>$' -F jaicompilertype.BucketArray" )
  C(  "type synthetic add  -w JaiCompiler Array_View64 -l jaicompilertype.ArrayChildrenProvider" )
  C( r"type synthetic add  -w JaiCompiler -x '^Array<.*>$' -l jaicompilertype.ResizableArrayChildrenProvider" )
  C( r"type synthetic add  -w JaiCompiler -x '^Local_Array<.*>$' -l jaicompilertype.ResizableLocalArrayChildrenProvider" )
  C( r"type synthetic add  -w JaiCompiler -x '^Bucket_Array<.*>$' -l jaicompilertype.BucketArrayChildrenProvider" )
  C(  'type category enable JaiCompiler' )

