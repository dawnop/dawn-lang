cuda_tile.module @m {
  entry @lora_hidden(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <f64: 0.0> : tile<32x16xf64>
    %2 = constant <i32: 0> : tile<i32>
    %3 = constant <i32: 2> : tile<i32>
    %4 = constant <i32: 1> : tile<i32>
    %5, %6 = for %7 in (%2 to %3, step %4) : tile<i32> iter_values(%8 = %1, %9 = %0) -> (tile<32x16xf64>, token) {
      %10 = constant <i32: 32> : tile<i32>
      %11 = muli %7, %10 : tile<i32>
      %12 = reshape %11 : tile<i32> -> tile<1x1xi32>
      %13 = broadcast %12 : tile<1x1xi32> -> tile<32x32xi32>
      %14 = iota : tile<32xi32>
      %15 = reshape %14 : tile<32xi32> -> tile<32x1xi32>
      %16 = broadcast %15 : tile<32x1xi32> -> tile<32x32xi32>
      %17 = constant <i32: 64> : tile<32x32xi32>
      %18 = muli %16, %17 : tile<32x32xi32>
      %19 = addi %13, %18 : tile<32x32xi32>
      %20 = iota : tile<32xi32>
      %21 = reshape %20 : tile<32xi32> -> tile<1x32xi32>
      %22 = broadcast %21 : tile<1x32xi32> -> tile<32x32xi32>
      %23 = addi %19, %22 : tile<32x32xi32>
      %24 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %25 = broadcast %24 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
      %26 = offset %25, %23 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
      %27, %28 = load_ptr_tko weak %26 token=%9 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
      %29 = constant <i32: 32> : tile<i32>
      %30 = muli %7, %29 : tile<i32>
      %31 = reshape %30 : tile<i32> -> tile<1x1xi32>
      %32 = broadcast %31 : tile<1x1xi32> -> tile<32x16xi32>
      %33 = iota : tile<32xi32>
      %34 = reshape %33 : tile<32xi32> -> tile<32x1xi32>
      %35 = broadcast %34 : tile<32x1xi32> -> tile<32x16xi32>
      %36 = addi %32, %35 : tile<32x16xi32>
      %37 = iota : tile<16xi32>
      %38 = reshape %37 : tile<16xi32> -> tile<1x16xi32>
      %39 = broadcast %38 : tile<1x16xi32> -> tile<32x16xi32>
      %40 = constant <i32: 64> : tile<32x16xi32>
      %41 = muli %39, %40 : tile<32x16xi32>
      %42 = addi %36, %41 : tile<32x16xi32>
      %43 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %44 = broadcast %43 : tile<1x1xptr<f64>> -> tile<32x16xptr<f64>>
      %45 = offset %44, %42 : tile<32x16xptr<f64>>, tile<32x16xi32> -> tile<32x16xptr<f64>>
      %46, %47 = load_ptr_tko weak %45 token=%28 : tile<32x16xptr<f64>> -> tile<32x16xf64>, token
      %48 = mmaf %27, %46, %8 : tile<32x32xf64>, tile<32x16xf64>, tile<32x16xf64>
      continue %48, %47 : tile<32x16xf64>, token
    }
    %49 = constant <i32: 0> : tile<i32>
    %50 = reshape %49 : tile<i32> -> tile<1x1xi32>
    %51 = broadcast %50 : tile<1x1xi32> -> tile<32x16xi32>
    %52 = iota : tile<32xi32>
    %53 = reshape %52 : tile<32xi32> -> tile<32x1xi32>
    %54 = broadcast %53 : tile<32x1xi32> -> tile<32x16xi32>
    %55 = constant <i32: 16> : tile<32x16xi32>
    %56 = muli %54, %55 : tile<32x16xi32>
    %57 = addi %51, %56 : tile<32x16xi32>
    %58 = iota : tile<16xi32>
    %59 = reshape %58 : tile<16xi32> -> tile<1x16xi32>
    %60 = broadcast %59 : tile<1x16xi32> -> tile<32x16xi32>
    %61 = addi %57, %60 : tile<32x16xi32>
    %62 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %63 = broadcast %62 : tile<1x1xptr<f64>> -> tile<32x16xptr<f64>>
    %64 = offset %63, %61 : tile<32x16xptr<f64>>, tile<32x16xi32> -> tile<32x16xptr<f64>>
    %65 = store_ptr_tko weak %64, %5 token=%6 : tile<32x16xptr<f64>>, tile<32x16xf64> -> token
    return
  }
}
