cuda_tile.module @m {
  entry @subarray_sum2d(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = reshape %1 : tile<i32> -> tile<1xi32>
    %3 = broadcast %2 : tile<1xi32> -> tile<2048xi32>
    %4 = iota : tile<2048xi32>
    %5 = addi %3, %4 : tile<2048xi32>
    %6 = constant <i32: 64> : tile<2048xi32>
    %7 = divi %5, %6 signed : tile<2048xi32>
    %8 = constant <i32: 5> : tile<2048xi32>
    %9 = cmpi greater_than_or_equal %7, %8, signed : tile<2048xi32> -> tile<2048xi1>
    %10 = constant <i32: 28> : tile<2048xi32>
    %11 = cmpi less_than %7, %10, signed : tile<2048xi32> -> tile<2048xi1>
    %12 = constant <i1: 0> : tile<2048xi1>
    %13 = select %9, %11, %12 : tile<2048xi1>, tile<2048xi1>
    %14 = remi %5, %6 signed : tile<2048xi32>
    %15 = constant <i32: 9> : tile<2048xi32>
    %16 = cmpi greater_than_or_equal %14, %15, signed : tile<2048xi32> -> tile<2048xi1>
    %17 = constant <i32: 53> : tile<2048xi32>
    %18 = cmpi less_than %14, %17, signed : tile<2048xi32> -> tile<2048xi1>
    %19 = constant <i1: 0> : tile<2048xi1>
    %20 = select %16, %18, %19 : tile<2048xi1>, tile<2048xi1>
    %21 = constant <i1: 0> : tile<2048xi1>
    %22 = select %13, %20, %21 : tile<2048xi1>, tile<2048xi1>
    %23 = constant <i32: 0> : tile<2048xi32>
    %24 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %25 = broadcast %24 : tile<1xptr<i32>> -> tile<2048xptr<i32>>
    %26 = offset %25, %5 : tile<2048xptr<i32>>, tile<2048xi32> -> tile<2048xptr<i32>>
    %27, %28 = load_ptr_tko weak %26, %22, %23 token=%0 : tile<2048xptr<i32>>, tile<2048xi1>, tile<2048xi32> -> tile<2048xi32>, token
    %29 = reduce %27 dim=0 identities=[0 : i32] : tile<2048xi32> -> tile<i32> (%30: tile<i32>, %31: tile<i32>) {
      %32 = addi %30, %31 : tile<i32>
      yield %32 : tile<i32>
    }
    %33 = reshape %29 : tile<i32> -> tile<1xi32>
    %34 = broadcast %33 : tile<1xi32> -> tile<1xi32>
    %35 = reshape %1 : tile<i32> -> tile<1xi32>
    %36 = broadcast %35 : tile<1xi32> -> tile<1xi32>
    %37 = iota : tile<1xi32>
    %38 = addi %36, %37 : tile<1xi32>
    %39 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %40 = broadcast %39 : tile<1xptr<i32>> -> tile<1xptr<i32>>
    %41 = offset %40, %38 : tile<1xptr<i32>>, tile<1xi32> -> tile<1xptr<i32>>
    %42 = store_ptr_tko weak %41, %34 token=%28 : tile<1xptr<i32>>, tile<1xi32> -> token
    return
  }
}
