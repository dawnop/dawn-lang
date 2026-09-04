cuda_tile.module @m {
  entry @lin_attn_s(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <f64: 0.0> : tile<32x32xf64>
    %2 = constant <i32: 0> : tile<i32>
    %3 = constant <i32: 2> : tile<i32>
    %4 = constant <i32: 1> : tile<i32>
    %5, %6 = for %7 in (%2 to %3, step %4) : tile<i32> iter_values(%8 = %1, %9 = %0) -> (tile<32x32xf64>, token) {
      %10 = constant <i32: 1024> : tile<i32>
      %11 = muli %7, %10 : tile<i32>
      %12 = reshape %11 : tile<i32> -> tile<1x1xi32>
      %13 = broadcast %12 : tile<1x1xi32> -> tile<32x32xi32>
      %14 = iota : tile<32xi32>
      %15 = reshape %14 : tile<32xi32> -> tile<32x1xi32>
      %16 = broadcast %15 : tile<32x1xi32> -> tile<32x32xi32>
      %17 = addi %13, %16 : tile<32x32xi32>
      %18 = iota : tile<32xi32>
      %19 = reshape %18 : tile<32xi32> -> tile<1x32xi32>
      %20 = broadcast %19 : tile<1x32xi32> -> tile<32x32xi32>
      %21 = constant <i32: 32> : tile<32x32xi32>
      %22 = muli %20, %21 : tile<32x32xi32>
      %23 = addi %17, %22 : tile<32x32xi32>
      %24 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %25 = broadcast %24 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
      %26 = offset %25, %23 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
      %27, %28 = load_ptr_tko weak %26 token=%9 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
      %29 = constant <i32: 1024> : tile<i32>
      %30 = muli %7, %29 : tile<i32>
      %31 = reshape %30 : tile<i32> -> tile<1x1xi32>
      %32 = broadcast %31 : tile<1x1xi32> -> tile<32x32xi32>
      %33 = iota : tile<32xi32>
      %34 = reshape %33 : tile<32xi32> -> tile<32x1xi32>
      %35 = broadcast %34 : tile<32x1xi32> -> tile<32x32xi32>
      %36 = constant <i32: 32> : tile<32x32xi32>
      %37 = muli %35, %36 : tile<32x32xi32>
      %38 = addi %32, %37 : tile<32x32xi32>
      %39 = iota : tile<32xi32>
      %40 = reshape %39 : tile<32xi32> -> tile<1x32xi32>
      %41 = broadcast %40 : tile<1x32xi32> -> tile<32x32xi32>
      %42 = addi %38, %41 : tile<32x32xi32>
      %43 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %44 = broadcast %43 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
      %45 = offset %44, %42 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
      %46, %47 = load_ptr_tko weak %45 token=%28 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
      %48 = constant <f64: 0.0> : tile<32x32xf64>
      %49 = cmpf greater_than ordered %27, %48 : tile<32x32xf64> -> tile<32x32xi1>
      %50 = constant <f64: 1.0> : tile<32x32xf64>
      %51 = addf %27, %50 rounding<nearest_even> : tile<32x32xf64>
      %52 = exp %27 : tile<32x32xf64>
      %53 = select %49, %51, %52 : tile<32x32xi1>, tile<32x32xf64>
      %54 = mmaf %53, %46, %8 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
      continue %54, %47 : tile<32x32xf64>, token
    }
    %55 = constant <i32: 0> : tile<i32>
    %56 = reshape %55 : tile<i32> -> tile<1x1xi32>
    %57 = broadcast %56 : tile<1x1xi32> -> tile<32x32xi32>
    %58 = iota : tile<32xi32>
    %59 = reshape %58 : tile<32xi32> -> tile<32x1xi32>
    %60 = broadcast %59 : tile<32x1xi32> -> tile<32x32xi32>
    %61 = constant <i32: 32> : tile<32x32xi32>
    %62 = muli %60, %61 : tile<32x32xi32>
    %63 = addi %57, %62 : tile<32x32xi32>
    %64 = iota : tile<32xi32>
    %65 = reshape %64 : tile<32xi32> -> tile<1x32xi32>
    %66 = broadcast %65 : tile<1x32xi32> -> tile<32x32xi32>
    %67 = addi %63, %66 : tile<32x32xi32>
    %68 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %69 = broadcast %68 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %70 = offset %69, %67 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %71 = store_ptr_tko weak %70, %5 token=%6 : tile<32x32xptr<f64>>, tile<32x32xf64> -> token
    return
  }
}
