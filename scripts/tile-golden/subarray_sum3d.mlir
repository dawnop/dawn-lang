cuda_tile.module @m {
  entry @subarray_sum3d(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = reshape %1 : tile<i32> -> tile<1xi32>
    %3 = broadcast %2 : tile<1xi32> -> tile<1024xi32>
    %4 = iota : tile<1024xi32>
    %5 = addi %3, %4 : tile<1024xi32>
    %6 = constant <i32: 32> : tile<1024xi32>
    %7 = constant <i32: 256> : tile<1024xi32>
    %8 = divi %5, %7 signed : tile<1024xi32>
    %9 = constant <i32: 1> : tile<1024xi32>
    %10 = cmpi greater_than_or_equal %8, %9, signed : tile<1024xi32> -> tile<1024xi1>
    %11 = constant <i32: 3> : tile<1024xi32>
    %12 = cmpi less_than %8, %11, signed : tile<1024xi32> -> tile<1024xi1>
    %13 = constant <i1: 0> : tile<1024xi1>
    %14 = select %10, %12, %13 : tile<1024xi1>, tile<1024xi1>
    %15 = divi %5, %6 signed : tile<1024xi32>
    %16 = constant <i32: 8> : tile<1024xi32>
    %17 = remi %15, %16 signed : tile<1024xi32>
    %18 = constant <i32: 2> : tile<1024xi32>
    %19 = cmpi greater_than_or_equal %17, %18, signed : tile<1024xi32> -> tile<1024xi1>
    %20 = constant <i32: 7> : tile<1024xi32>
    %21 = cmpi less_than %17, %20, signed : tile<1024xi32> -> tile<1024xi1>
    %22 = constant <i1: 0> : tile<1024xi1>
    %23 = select %19, %21, %22 : tile<1024xi1>, tile<1024xi1>
    %24 = constant <i1: 0> : tile<1024xi1>
    %25 = select %14, %23, %24 : tile<1024xi1>, tile<1024xi1>
    %26 = remi %5, %6 signed : tile<1024xi32>
    %27 = constant <i32: 3> : tile<1024xi32>
    %28 = cmpi greater_than_or_equal %26, %27, signed : tile<1024xi32> -> tile<1024xi1>
    %29 = constant <i32: 30> : tile<1024xi32>
    %30 = cmpi less_than %26, %29, signed : tile<1024xi32> -> tile<1024xi1>
    %31 = constant <i1: 0> : tile<1024xi1>
    %32 = select %28, %30, %31 : tile<1024xi1>, tile<1024xi1>
    %33 = constant <i1: 0> : tile<1024xi1>
    %34 = select %25, %32, %33 : tile<1024xi1>, tile<1024xi1>
    %35 = constant <i32: 0> : tile<1024xi32>
    %36 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %37 = broadcast %36 : tile<1xptr<i32>> -> tile<1024xptr<i32>>
    %38 = offset %37, %5 : tile<1024xptr<i32>>, tile<1024xi32> -> tile<1024xptr<i32>>
    %39, %40 = load_ptr_tko weak %38, %34, %35 token=%0 : tile<1024xptr<i32>>, tile<1024xi1>, tile<1024xi32> -> tile<1024xi32>, token
    %41 = reduce %39 dim=0 identities=[0 : i32] : tile<1024xi32> -> tile<i32> (%42: tile<i32>, %43: tile<i32>) {
      %44 = addi %42, %43 : tile<i32>
      yield %44 : tile<i32>
    }
    %45 = reshape %41 : tile<i32> -> tile<1xi32>
    %46 = broadcast %45 : tile<1xi32> -> tile<1xi32>
    %47 = reshape %1 : tile<i32> -> tile<1xi32>
    %48 = broadcast %47 : tile<1xi32> -> tile<1xi32>
    %49 = iota : tile<1xi32>
    %50 = addi %48, %49 : tile<1xi32>
    %51 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %52 = broadcast %51 : tile<1xptr<i32>> -> tile<1xptr<i32>>
    %53 = offset %52, %50 : tile<1xptr<i32>>, tile<1xi32> -> tile<1xptr<i32>>
    %54 = store_ptr_tko weak %53, %46 token=%40 : tile<1xptr<i32>>, tile<1xi32> -> token
    return
  }
}
