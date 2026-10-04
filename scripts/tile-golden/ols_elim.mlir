cuda_tile.module @m {
  entry @ols_elim(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = offset %arg1, %1 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %3, %4 = load_ptr_tko weak %2 token=%0 : tile<ptr<i32>> -> tile<i32>, token
    %5 = constant <i32: 0> : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1x1xi32>
    %7 = broadcast %6 : tile<1x1xi32> -> tile<8x16xi32>
    %8 = iota : tile<8xi32>
    %9 = reshape %8 : tile<8xi32> -> tile<8x1xi32>
    %10 = broadcast %9 : tile<8x1xi32> -> tile<8x16xi32>
    %11 = addi %7, %10 : tile<8x16xi32>
    %12 = iota : tile<16xi32>
    %13 = reshape %12 : tile<16xi32> -> tile<1x16xi32>
    %14 = broadcast %13 : tile<1x16xi32> -> tile<8x16xi32>
    %15 = constant <i32: 0> : tile<8x16xi32>
    %16 = muli %14, %15 : tile<8x16xi32>
    %17 = addi %11, %16 : tile<8x16xi32>
    %18 = constant <i32: 0> : tile<i32>
    %19 = reshape %18 : tile<i32> -> tile<1x1xi32>
    %20 = broadcast %19 : tile<1x1xi32> -> tile<8x16xi32>
    %21 = iota : tile<8xi32>
    %22 = reshape %21 : tile<8xi32> -> tile<8x1xi32>
    %23 = broadcast %22 : tile<8x1xi32> -> tile<8x16xi32>
    %24 = constant <i32: 0> : tile<8x16xi32>
    %25 = muli %23, %24 : tile<8x16xi32>
    %26 = addi %20, %25 : tile<8x16xi32>
    %27 = iota : tile<16xi32>
    %28 = reshape %27 : tile<16xi32> -> tile<1x16xi32>
    %29 = broadcast %28 : tile<1x16xi32> -> tile<8x16xi32>
    %30 = addi %26, %29 : tile<8x16xi32>
    %31 = constant <i32: 16> : tile<i32>
    %32 = muli %3, %31 : tile<i32>
    %33 = addi %32, %3 : tile<i32>
    %34 = offset %arg0, %33 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %35, %36 = load_ptr_tko weak %34 token=%4 : tile<ptr<f64>> -> tile<f64>, token
    %37 = reshape %32 : tile<i32> -> tile<1x1xi32>
    %38 = broadcast %37 : tile<1x1xi32> -> tile<8x16xi32>
    %39 = addi %38, %30 : tile<8x16xi32>
    %40 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %41 = broadcast %40 : tile<1x1xptr<f64>> -> tile<8x16xptr<f64>>
    %42 = offset %41, %39 : tile<8x16xptr<f64>>, tile<8x16xi32> -> tile<8x16xptr<f64>>
    %43, %44 = load_ptr_tko weak %42 token=%36 : tile<8x16xptr<f64>> -> tile<8x16xf64>, token
    %45 = reshape %35 : tile<f64> -> tile<1x1xf64>
    %46 = broadcast %45 : tile<1x1xf64> -> tile<8x16xf64>
    %47 = divf %43, %46 rounding<nearest_even> : tile<8x16xf64>
    %48 = constant <i32: 16> : tile<8x16xi32>
    %49 = muli %17, %48 : tile<8x16xi32>
    %50 = reshape %3 : tile<i32> -> tile<1x1xi32>
    %51 = broadcast %50 : tile<1x1xi32> -> tile<8x16xi32>
    %52 = addi %49, %51 : tile<8x16xi32>
    %53 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %54 = broadcast %53 : tile<1x1xptr<f64>> -> tile<8x16xptr<f64>>
    %55 = offset %54, %52 : tile<8x16xptr<f64>>, tile<8x16xi32> -> tile<8x16xptr<f64>>
    %56, %57 = load_ptr_tko weak %55 token=%44 : tile<8x16xptr<f64>> -> tile<8x16xf64>, token
    %58 = constant <i32: 0> : tile<i32>
    %59 = reshape %58 : tile<i32> -> tile<1x1xi32>
    %60 = broadcast %59 : tile<1x1xi32> -> tile<8x16xi32>
    %61 = iota : tile<8xi32>
    %62 = reshape %61 : tile<8xi32> -> tile<8x1xi32>
    %63 = broadcast %62 : tile<8x1xi32> -> tile<8x16xi32>
    %64 = constant <i32: 16> : tile<8x16xi32>
    %65 = muli %63, %64 : tile<8x16xi32>
    %66 = addi %60, %65 : tile<8x16xi32>
    %67 = iota : tile<16xi32>
    %68 = reshape %67 : tile<16xi32> -> tile<1x16xi32>
    %69 = broadcast %68 : tile<1x16xi32> -> tile<8x16xi32>
    %70 = addi %66, %69 : tile<8x16xi32>
    %71 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %72 = broadcast %71 : tile<1x1xptr<f64>> -> tile<8x16xptr<f64>>
    %73 = offset %72, %70 : tile<8x16xptr<f64>>, tile<8x16xi32> -> tile<8x16xptr<f64>>
    %74, %75 = load_ptr_tko weak %73 token=%57 : tile<8x16xptr<f64>> -> tile<8x16xf64>, token
    %76 = mulf %56, %47 rounding<nearest_even> : tile<8x16xf64>
    %77 = subf %74, %76 rounding<nearest_even> : tile<8x16xf64>
    %78 = constant <i32: 0> : tile<i32>
    %79 = cmpi equal %17, %51, signed : tile<8x16xi32> -> tile<8x16xi1>
    %80 = select %79, %47, %77 : tile<8x16xi1>, tile<8x16xf64>
    %81 = reshape %78 : tile<i32> -> tile<1x1xi32>
    %82 = broadcast %81 : tile<1x1xi32> -> tile<8x16xi32>
    %83 = iota : tile<8xi32>
    %84 = reshape %83 : tile<8xi32> -> tile<8x1xi32>
    %85 = broadcast %84 : tile<8x1xi32> -> tile<8x16xi32>
    %86 = constant <i32: 16> : tile<8x16xi32>
    %87 = muli %85, %86 : tile<8x16xi32>
    %88 = addi %82, %87 : tile<8x16xi32>
    %89 = iota : tile<16xi32>
    %90 = reshape %89 : tile<16xi32> -> tile<1x16xi32>
    %91 = broadcast %90 : tile<1x16xi32> -> tile<8x16xi32>
    %92 = addi %88, %91 : tile<8x16xi32>
    %93 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %94 = broadcast %93 : tile<1x1xptr<f64>> -> tile<8x16xptr<f64>>
    %95 = offset %94, %92 : tile<8x16xptr<f64>>, tile<8x16xi32> -> tile<8x16xptr<f64>>
    %96 = store_ptr_tko weak %95, %80 token=%75 : tile<8x16xptr<f64>>, tile<8x16xf64> -> token
    return
  }
}
