cuda_tile.module @m {
  entry @dequant(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = constant <i32: 16> : tile<64x64xi32>
    %3 = reshape %1 : tile<i32> -> tile<1x1xi32>
    %4 = broadcast %3 : tile<1x1xi32> -> tile<64x64xi32>
    %5 = iota : tile<64xi32>
    %6 = reshape %5 : tile<64xi32> -> tile<64x1xi32>
    %7 = broadcast %6 : tile<64x1xi32> -> tile<64x64xi32>
    %8 = addi %4, %7 : tile<64x64xi32>
    %9 = iota : tile<64xi32>
    %10 = reshape %9 : tile<64xi32> -> tile<1x64xi32>
    %11 = broadcast %10 : tile<1x64xi32> -> tile<64x64xi32>
    %12 = constant <i32: 0> : tile<64x64xi32>
    %13 = muli %11, %12 : tile<64x64xi32>
    %14 = addi %8, %13 : tile<64x64xi32>
    %15 = divi %14, %2 signed : tile<64x64xi32>
    %16 = constant <i32: 4> : tile<64x64xi32>
    %17 = muli %15, %16 : tile<64x64xi32>
    %18 = reshape %1 : tile<i32> -> tile<1x1xi32>
    %19 = broadcast %18 : tile<1x1xi32> -> tile<64x64xi32>
    %20 = iota : tile<64xi32>
    %21 = reshape %20 : tile<64xi32> -> tile<64x1xi32>
    %22 = broadcast %21 : tile<64x1xi32> -> tile<64x64xi32>
    %23 = constant <i32: 0> : tile<64x64xi32>
    %24 = muli %22, %23 : tile<64x64xi32>
    %25 = addi %19, %24 : tile<64x64xi32>
    %26 = iota : tile<64xi32>
    %27 = reshape %26 : tile<64xi32> -> tile<1x64xi32>
    %28 = broadcast %27 : tile<1x64xi32> -> tile<64x64xi32>
    %29 = addi %25, %28 : tile<64x64xi32>
    %30 = divi %29, %2 signed : tile<64x64xi32>
    %31 = addi %17, %30 : tile<64x64xi32>
    %32 = reshape %1 : tile<i32> -> tile<1x1xi32>
    %33 = broadcast %32 : tile<1x1xi32> -> tile<64x64xi32>
    %34 = iota : tile<64xi32>
    %35 = reshape %34 : tile<64xi32> -> tile<64x1xi32>
    %36 = broadcast %35 : tile<64x1xi32> -> tile<64x64xi32>
    %37 = constant <i32: 64> : tile<64x64xi32>
    %38 = muli %36, %37 : tile<64x64xi32>
    %39 = addi %33, %38 : tile<64x64xi32>
    %40 = iota : tile<64xi32>
    %41 = reshape %40 : tile<64xi32> -> tile<1x64xi32>
    %42 = broadcast %41 : tile<1x64xi32> -> tile<64x64xi32>
    %43 = addi %39, %42 : tile<64x64xi32>
    %44 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %45 = broadcast %44 : tile<1x1xptr<f64>> -> tile<64x64xptr<f64>>
    %46 = offset %45, %43 : tile<64x64xptr<f64>>, tile<64x64xi32> -> tile<64x64xptr<f64>>
    %47, %48 = load_ptr_tko weak %46 token=%0 : tile<64x64xptr<f64>> -> tile<64x64xf64>, token
    %49 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %50 = broadcast %49 : tile<1x1xptr<f64>> -> tile<64x64xptr<f64>>
    %51 = offset %50, %31 : tile<64x64xptr<f64>>, tile<64x64xi32> -> tile<64x64xptr<f64>>
    %52, %53 = load_ptr_tko weak %51 token=%48 : tile<64x64xptr<f64>> -> tile<64x64xf64>, token
    %54 = mulf %47, %52 rounding<nearest_even> : tile<64x64xf64>
    %55 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %56 = broadcast %55 : tile<1x1xptr<f64>> -> tile<64x64xptr<f64>>
    %57 = offset %56, %43 : tile<64x64xptr<f64>>, tile<64x64xi32> -> tile<64x64xptr<f64>>
    %58 = store_ptr_tko weak %57, %54 token=%53 : tile<64x64xptr<f64>>, tile<64x64xf64> -> token
    return
  }
}
