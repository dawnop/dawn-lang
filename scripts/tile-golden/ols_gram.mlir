cuda_tile.module @m {
  entry @ols_gram(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = reshape %1 : tile<i32> -> tile<1x1xi32>
    %3 = broadcast %2 : tile<1x1xi32> -> tile<8x16xi32>
    %4 = iota : tile<8xi32>
    %5 = reshape %4 : tile<8xi32> -> tile<8x1xi32>
    %6 = broadcast %5 : tile<8x1xi32> -> tile<8x16xi32>
    %7 = constant <i32: 0> : tile<8x16xi32>
    %8 = muli %6, %7 : tile<8x16xi32>
    %9 = addi %3, %8 : tile<8x16xi32>
    %10 = iota : tile<16xi32>
    %11 = reshape %10 : tile<16xi32> -> tile<1x16xi32>
    %12 = broadcast %11 : tile<1x16xi32> -> tile<8x16xi32>
    %13 = addi %9, %12 : tile<8x16xi32>
    %14 = constant <i32: 8> : tile<8x16xi32>
    %15 = cmpi less_than %13, %14, signed : tile<8x16xi32> -> tile<8x16xi1>
    %16 = constant <i32: 8> : tile<8x16xi32>
    %17 = cmpi equal %13, %16, signed : tile<8x16xi32> -> tile<8x16xi1>
    %18 = constant <f64: 0.0> : tile<8x16xf64>
    %19 = constant <i32: 0> : tile<i32>
    %20 = constant <i32: 64> : tile<i32>
    %21 = constant <i32: 1> : tile<i32>
    %22, %23 = for %24 in (%19 to %20, step %21) : tile<i32> iter_values(%25 = %18, %26 = %0) -> (tile<8x16xf64>, token) {
      %27 = constant <i32: 8> : tile<i32>
      %28 = muli %24, %27 : tile<i32>
      %29 = reshape %28 : tile<i32> -> tile<1x1xi32>
      %30 = broadcast %29 : tile<1x1xi32> -> tile<8x16xi32>
      %31 = iota : tile<8xi32>
      %32 = reshape %31 : tile<8xi32> -> tile<8x1xi32>
      %33 = broadcast %32 : tile<8x1xi32> -> tile<8x16xi32>
      %34 = addi %30, %33 : tile<8x16xi32>
      %35 = iota : tile<16xi32>
      %36 = reshape %35 : tile<16xi32> -> tile<1x16xi32>
      %37 = broadcast %36 : tile<1x16xi32> -> tile<8x16xi32>
      %38 = constant <i32: 0> : tile<8x16xi32>
      %39 = muli %37, %38 : tile<8x16xi32>
      %40 = addi %34, %39 : tile<8x16xi32>
      %41 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %42 = broadcast %41 : tile<1x1xptr<f64>> -> tile<8x16xptr<f64>>
      %43 = offset %42, %40 : tile<8x16xptr<f64>>, tile<8x16xi32> -> tile<8x16xptr<f64>>
      %44, %45 = load_ptr_tko weak %43 token=%26 : tile<8x16xptr<f64>> -> tile<8x16xf64>, token
      %46 = reshape %28 : tile<i32> -> tile<1x1xi32>
      %47 = broadcast %46 : tile<1x1xi32> -> tile<8x16xi32>
      %48 = iota : tile<8xi32>
      %49 = reshape %48 : tile<8xi32> -> tile<8x1xi32>
      %50 = broadcast %49 : tile<8x1xi32> -> tile<8x16xi32>
      %51 = constant <i32: 0> : tile<8x16xi32>
      %52 = muli %50, %51 : tile<8x16xi32>
      %53 = addi %47, %52 : tile<8x16xi32>
      %54 = iota : tile<16xi32>
      %55 = reshape %54 : tile<16xi32> -> tile<1x16xi32>
      %56 = broadcast %55 : tile<1x16xi32> -> tile<8x16xi32>
      %57 = addi %53, %56 : tile<8x16xi32>
      %58 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %59 = broadcast %58 : tile<1x1xptr<f64>> -> tile<8x16xptr<f64>>
      %60 = offset %59, %57 : tile<8x16xptr<f64>>, tile<8x16xi32> -> tile<8x16xptr<f64>>
      %61, %62 = load_ptr_tko weak %60, %15, %18 token=%45 : tile<8x16xptr<f64>>, tile<8x16xi1>, tile<8x16xf64> -> tile<8x16xf64>, token
      %63 = reshape %24 : tile<i32> -> tile<1x1xi32>
      %64 = broadcast %63 : tile<1x1xi32> -> tile<8x16xi32>
      %65 = iota : tile<8xi32>
      %66 = reshape %65 : tile<8xi32> -> tile<8x1xi32>
      %67 = broadcast %66 : tile<8x1xi32> -> tile<8x16xi32>
      %68 = constant <i32: 0> : tile<8x16xi32>
      %69 = muli %67, %68 : tile<8x16xi32>
      %70 = addi %64, %69 : tile<8x16xi32>
      %71 = iota : tile<16xi32>
      %72 = reshape %71 : tile<16xi32> -> tile<1x16xi32>
      %73 = broadcast %72 : tile<1x16xi32> -> tile<8x16xi32>
      %74 = constant <i32: 0> : tile<8x16xi32>
      %75 = muli %73, %74 : tile<8x16xi32>
      %76 = addi %70, %75 : tile<8x16xi32>
      %77 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %78 = broadcast %77 : tile<1x1xptr<f64>> -> tile<8x16xptr<f64>>
      %79 = offset %78, %76 : tile<8x16xptr<f64>>, tile<8x16xi32> -> tile<8x16xptr<f64>>
      %80, %81 = load_ptr_tko weak %79 token=%62 : tile<8x16xptr<f64>> -> tile<8x16xf64>, token
      %82 = select %17, %80, %61 : tile<8x16xi1>, tile<8x16xf64>
      %83 = mulf %44, %82 rounding<nearest_even> : tile<8x16xf64>
      %84 = addf %25, %83 rounding<nearest_even> : tile<8x16xf64>
      continue %84, %81 : tile<8x16xf64>, token
    }
    %85 = constant <i32: 0> : tile<i32>
    %86 = reshape %85 : tile<i32> -> tile<1x1xi32>
    %87 = broadcast %86 : tile<1x1xi32> -> tile<8x16xi32>
    %88 = iota : tile<8xi32>
    %89 = reshape %88 : tile<8xi32> -> tile<8x1xi32>
    %90 = broadcast %89 : tile<8x1xi32> -> tile<8x16xi32>
    %91 = constant <i32: 16> : tile<8x16xi32>
    %92 = muli %90, %91 : tile<8x16xi32>
    %93 = addi %87, %92 : tile<8x16xi32>
    %94 = iota : tile<16xi32>
    %95 = reshape %94 : tile<16xi32> -> tile<1x16xi32>
    %96 = broadcast %95 : tile<1x16xi32> -> tile<8x16xi32>
    %97 = addi %93, %96 : tile<8x16xi32>
    %98 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %99 = broadcast %98 : tile<1x1xptr<f64>> -> tile<8x16xptr<f64>>
    %100 = offset %99, %97 : tile<8x16xptr<f64>>, tile<8x16xi32> -> tile<8x16xptr<f64>>
    %101 = store_ptr_tko weak %100, %22 token=%23 : tile<8x16xptr<f64>>, tile<8x16xf64> -> token
    return
  }
}
