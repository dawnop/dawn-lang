cuda_tile.module @m {
  entry @dot_f16(%arg0: tile<ptr<f16>>, %arg1: tile<ptr<f16>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 1024> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<1024xi32>
    %8 = iota : tile<1024xi32>
    %9 = addi %7, %8 : tile<1024xi32>
    %10 = constant <i32: 1000> : tile<1024xi32>
    %11 = cmpi less_than %9, %10, signed : tile<1024xi32> -> tile<1024xi1>
    %12 = constant <f16: 0.0> : tile<1024xf16>
    %13 = reshape %arg0 : tile<ptr<f16>> -> tile<1xptr<f16>>
    %14 = broadcast %13 : tile<1xptr<f16>> -> tile<1024xptr<f16>>
    %15 = offset %14, %9 : tile<1024xptr<f16>>, tile<1024xi32> -> tile<1024xptr<f16>>
    %16, %17 = load_ptr_tko weak %15, %11, %12 token=%0 : tile<1024xptr<f16>>, tile<1024xi1>, tile<1024xf16> -> tile<1024xf16>, token
    %18 = ftof %16 rounding<nearest_even> : tile<1024xf16> -> tile<1024xf64>
    %19 = reshape %arg1 : tile<ptr<f16>> -> tile<1xptr<f16>>
    %20 = broadcast %19 : tile<1xptr<f16>> -> tile<1024xptr<f16>>
    %21 = offset %20, %9 : tile<1024xptr<f16>>, tile<1024xi32> -> tile<1024xptr<f16>>
    %22, %23 = load_ptr_tko weak %21, %11, %12 token=%17 : tile<1024xptr<f16>>, tile<1024xi1>, tile<1024xf16> -> tile<1024xf16>, token
    %24 = ftof %22 rounding<nearest_even> : tile<1024xf16> -> tile<1024xf64>
    %25 = mulf %18, %24 rounding<nearest_even> : tile<1024xf64>
    %26 = constant <i32: 1> : tile<i32>
    %27 = muli %1, %26 : tile<i32>
    %28 = reduce %25 dim=0 identities=[0.0 : f64] : tile<1024xf64> -> tile<f64> (%29: tile<f64>, %30: tile<f64>) {
      %31 = addf %29, %30 rounding<nearest_even> : tile<f64>
      yield %31 : tile<f64>
    }
    %32 = reshape %28 : tile<f64> -> tile<1xf64>
    %33 = broadcast %32 : tile<1xf64> -> tile<1xf64>
    %34 = reshape %27 : tile<i32> -> tile<1xi32>
    %35 = broadcast %34 : tile<1xi32> -> tile<1xi32>
    %36 = iota : tile<1xi32>
    %37 = addi %35, %36 : tile<1xi32>
    %38 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %39 = broadcast %38 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %40 = offset %39, %37 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %41 = store_ptr_tko weak %40, %33 token=%23 : tile<1xptr<f64>>, tile<1xf64> -> token
    return
  }
}
